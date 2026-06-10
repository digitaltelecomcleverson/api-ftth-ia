import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Motor FTTH Profissional - Validação Rígida PON e Linhas ASU")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta", "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"]

class Coordenada(BaseModel):
    lat: float
    lng: float

class ElementoManual(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    ceo_vinculo: int

class RequestProjetoEngenharia(BaseModel):
    olt: Coordenada
    ceos: List[ElementoManual]
    ctos: List[ElementoManual]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor de Engenharia FTTH Ativo e Validado"}

@app.post("/api/v1/calcular")
async def calcular_rede_engenharia(dados: RequestProjetoEngenharia):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma Caixa de Emenda (CEO).")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante caixas CTO para traçar o cabeamento.")

    # VALIDAÇÃO RÍGIDA 1: Limite de atendimento do Splitter da CEO por Porta PON
    limite_caixas_pon = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    
    # Verifica cada PON individualmente
    for ceo_verif in dados.ceos:
        qtd_ctos_na_pon = len([c for c in dados.ctos if c.ceo_vinculo == ceo_verif.id and c.pon_id == ceo_verif.pon_id])
        if qtd_ctos_na_pon > limite_caixas_pon:
            raise HTTPException(
                status_code=400, 
                detail=f"Bloqueio de Engenharia: A PON {ceo_verif.pon_id} está com {qtd_ctos_na_pon} CTOs implantadas. O splitter {dados.splitter_ceo} configurado na CEO suporta no máximo {limite_caixas_pon} caixas! Mude as caixas excedentes para outra Porta PON."
            )

    try:
        kml = simplekml.Kml(name="Projeto Executivo - Digital Telecom")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        # Desenha os cabos alimentadores das CEOs (Backbone)
        for ceo in dados.ceos:
            pnt_c = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt_c.description = f"<h3>CEO {ceo.id:02d}</h3><p><b>Porta Atendida:</b> PON {ceo.pon_id}</p><p><b>Splitter Primário:</b> {dados.splitter_ceo}</p>"
            
            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff"

        response_ctos = []

        # 2. PROCESSAMENTO DIRECIONAL POR CABO (SEM ZIGUE-ZAGUE / SEM RETORNO)
        for ceo in dados.ceos:
            ctos_da_ceo = [c for c in dados.ctos if c.ceo_vinculo == ceo.id and c.pon_id == ceo.pon_id]
            if not ctos_da_ceo: continue

            # Classifica e separa as CTOs por "Lado/Direção" usando agrupamento vetorial angular (Rua por Rua)
            # Desta forma, caixas em direções opostas ganham cabos independentes saindo da CEO
            coords_ctos = np.array([[c.lat, c.lng] for c in ctos_da_ceo])
            ceo_pt = np.array([ceo.lat, ceo.lng])
            
            angulos = np.array([np.arctan2(c[0] - ceo_pt[0], c[1] - ceo_pt[1]) for c in coords_ctos])
            
            # Define quantas direções/ruas distintas existem (mínimo 1, máximo 4 saídas de cabos por CEO)
            qtd_direcoes = min(4, len(ctos_da_ceo))
            from sklearn.cluster import KMeans
            kmeans_dir = KMeans(n_clusters=qtd_direcoes, random_state=42, n_init=10)
            kmeans_dir.fit(angulos.reshape(-1, 1))
            labels_direcoes = kmeans_dir.labels_

            # Processa cada cabo/rua independente saindo da CEO
            for d_idx in range(qtd_direcoes):
                indices_da_rua = [idx for idx, lbl in enumerate(labels_direcoes) if lbl == d_idx]
                if not indices_da_rua: continue

                ctos_desta_rua = [ctos_da_ceo[idx] for idx in indices_da_rua]
                
                # Ordena as caixas em linha reta estrita, do início da rua (perto da CEO) para o fim da rua
                ctos_desta_rua.sort(key=lambda c: (c.lat - ceo.lat)**2 + (c.lng - ceo.lng)**2)

                # Regra de Engenharia: Define a bitola do cabo baseado estritamente na quantidade dessa linha reta
                qtd_na_linha = len(ctos_desta_rua)
                tipo_cabo = "12FO (ASU-120)" if qtd_na_linha > 6 else "6FO (ASU-80)"

                pt_anterior_lat = ceo.lat
                pt_anterior_lng = ceo.lng
                dist_acumulada_linha = 0.0
                dist_base_ceo = np.sqrt((ceo.lat - dados.olt.lat)**2 + (ceo.lng - dados.olt.lng)**2) * 111.32

                for seq_pos, cto in enumerate(ctos_desta_rua):
                    fibra_num = seq_pos + 1
                    cor_fibra = CORES_ANATEL[seq_pos % len(CORES_ANATEL)]

                    # Cálculo cumulativo de perda na rota física (sentido correto)
                    d_trecho = np.sqrt((cto.lat - pt_anterior_lat)**2 + (cto.lng - pt_anterior_lng)**2) * 111.32
                    dist_acumulada_linha += d_trecho
                    dist_total = dist_base_ceo + dist_acumulada_linha
                    potencia = dados.potencia_olt - ((dist_total * 0.35) + 10.5 + 10.5 + 0.6)

                    # Unifilar interno no KML
                    html_cto = f"""
                    <div style="font-family:sans-serif; width:290px; color:#333;">
                        <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 UNIFILAR - CTO {cto.id:02d}</h3>
                        <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                            <p><b>Porta Ativa:</b> PON {cto.pon_id:02d}</p>
                            <p><b>Caixa de Emenda:</b> CEO {ceo.id:02d}</p>
                            <p><b>Modelo do Cabo Lançado:</b> Cabo Distribuição {tipo_cabo}</p>
                            <p style="color:#2563eb; font-weight:bold;">✂️ Fusão / Sangria: Fibra 0{fibra_num} ({cor_fibra})</p>
                            <p style="color:#666;">Fibras subsequentes seguem passantes e limpas no tubo loose.</p>
                            <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                            <p><b>Nível de Sinal Estimado:</b> <b>{potencia:.2f} dBm</b></p>
                        </div>
                    </div>
                    """
                    pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
                    pnt_cto.description = html_cto

                    # Desenha a seção do cabo unindo os postes em linha reta (sem voltar e sem cruzar)
                    lin_c = fol_cabos_root.newlinestring(name=f"Cabo PON {cto.pon_id:02d} - Rota {d_idx+1}")
                    lin_c.coords = [(pt_anterior_lng, pt_anterior_lat), (cto.lng, cto.lat)]
                    lin_c.style.linestyle.width = 3
                    lin_c.style.linestyle.color = "ff00ff00" # Verde Distribuição

                    response_ctos.append({
                        "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id, "ceo_vinculo": ceo.id,
                        "potencia_dbm": round(potencia, 2), "cabo_utilizado": tipo_cabo, "fibra_sangrada": f"Fibra {fibra_num} ({cor_fibra})"
                    })

                    # Avança o cabo para a próxima caixa na mesma linha reta
                    pt_anterior_lat = cto.lat
                    pt_anterior_lng = cto.lng

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor de engenharia: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

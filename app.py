import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Motor FTTH - Multi-PON com Upgrade 6FO/12FO")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 3.8, "1x4": 7.2, "1x8": 10.5, "1x16": 13.8, "1x32": 17.0}
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

class RequestProjetoProfissional(BaseModel):
    olt: Coordenada
    ceos: List[ElementoManual]
    ctos: List[ElementoManual]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor FTTH Profissional Multi-PON Online"}

@app.post("/api/v1/calcular")
async def calcular_rede_profissional(dados: RequestProjetoProfissional):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma Caixa de Emenda (CEO).")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante caixas CTO no mapa para traçar os cabos.")

    try:
        kml = simplekml.Kml(name="Projeto Executivo FTTH - Digital Telecom")
        
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Tronco OLT)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)

        # 1. DOCUMENTAÇÃO E DESENHO DOS CABOS TRONCO (OLT -> CEOs)
        for ceo in dados.ceos:
            dist_tronco = np.sqrt((ceo.lat - dados.olt.lat)**2 + (ceo.lng - dados.olt.lng)**2) * 111.32
            
            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff" # Vermelho

            pnt_c = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt_c.description = f"<h3>Caixa de Emenda CEO {ceo.id:02d}</h3><p><b>Porta PON Atendida:</b> PON {ceo.pon_id}</p><p>Splitter 1º Nível: {dados.splitter_ceo}</p>"

        response_ctos = []

        # 2. PROCESSAMENTO SEQUENCIAL DOS CABOS POR RAMAL PON E POR CEO (RUA POR RUA)
        # O cabo seguirá estritamente a ordem linear em que o usuário clicou
        for ceo in dados.ceos:
            # Filtra todas as CTOs que pertencem a esta caixa de emenda específica
            ctos_do_ramal = [c for c in dados.ctos if c.ceo_vinculo == ceo.id and c.pon_id == ceo.pon_id]
            if not ctos_do_ramal: continue

            # Determina a bitola do cabo baseado na quantidade de caixas em linha na rua
            qtd_caixas = len(ctos_do_ramal)
            tipo_cabo = "12FO (ASU-120)" if qtd_caixas > 6 else "6FO (ASU-80)"
            
            pt_anterior_lat = ceo.lat
            pt_anterior_lng = ceo.lng
            dist_acumulada_ramal = 0.0

            # Distância base do Tronco até essa CEO
            dist_base_ceo = np.sqrt((ceo.lat - dados.olt.lat)**2 + (ceo.lng - dados.olt.lng)**2) * 111.32

            for seq_idx, cto in enumerate(ctos_do_ramal):
                # Determina a cor da fibra pela sequência exata do cabo (Padrão Anatel 1 a 12)
                fibra_numero = seq_idx + 1
                cor_fibra = CORES_ANATEL[seq_idx % len(CORES_ANATEL)]

                # Orçamento de potência cumulativo na rota física
                d_trecho = np.sqrt((cto.lat - pt_anterior_lat)**2 + (cto.lng - pt_anterior_lng)**2) * 111.32
                dist_acumulada_ramal += d_trecho
                dist_total_fibra = dist_base_ceo + dist_acumulada_ramal
                
                perda_fibra = dist_total_fibra * 0.35
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.6
                potencia_final = dados.potencia_olt - perda_total

                # Criação do documento unifilar da CTO no KML
                html_cto = f"""
                <div style="font-family:sans-serif; width:300px; color:#333;">
                    <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 UNIFILAR - CTO {cto.id:02d}</h3>
                    <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                        <p><b>Porta OLT:</b> PON {cto.pon_id:02d}</p>
                        <p><b>Alimentada por:</b> CEO {ceo.id:02d}</p>
                        <p><b>Modelo do Cabo da Rua:</b> Cabo Distribuição {tipo_cabo}</p>
                        <p style="color:#2563eb; font-weight:bold;">✂️ Sangria Ativa: Fibra 0{fibra_numero} ({cor_fibra})</p>
                        <p style="color:#666;">Fibras restantes seguem passantes e protegidas no tubo loose.</p>
                        <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                        <p><b>Sinal Estimado no Atendimento:</b> <span style="color:#16a34a; font-weight:bold;">{potencia_final:.2f} dBm</span></p>
                    </div>
                </div>
                """

                pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
                pnt_cto.description = html_cto

                # Traçado de cabo linear sem zigue-zague (une os pontos na ordem exata do clique)
                lin_d = fol_cabos_root.newlinestring(name=f"Cabo PON {cto.pon_id:02d} - Trecho {seq_idx+1}")
                lin_d.coords = [(pt_anterior_lng, pt_anterior_lat), (cto.lng, cto.lat)]
                lin_d.style.linestyle.width = 3
                lin_d.style.linestyle.color = "ff00ff00" # Verde Distribuição

                response_ctos.append({
                    "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id,
                    "potencia_dbm": round(potencia_final, 2), "cabo_utilizado": tipo_cabo, "fibra_sangrada": f"Fibra {fibra_numero} ({cor_fibra})"
                })

                # Avança o ponto de ancoragem para a próxima caixa do posteamento
                pt_anterior_lat = cto.lat
                pt_anterior_lng = cto.lng

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor profissional: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH - Sangria 6FO em Barramento")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 3.8, "1x4": 7.2, "1x8": 10.5, "1x16": 13.8, "1x32": 17.0}
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta"]

class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjetoPoligono(BaseModel):
    olt: Coordenada
    poligono: List[Coordenada]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor de Sangria 6FO Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede_poligono(dados: RequestProjetoPoligono):
    if len(dados.poligono) < 3:
        raise HTTPException(status_code=400, detail="Demarque uma área válida.")

    try:
        lats = [pt.lat for pt in dados.poligono]
        lngs = [pt.lng for pt in dados.poligono]
        
        # Simulação concentrada para alinhar os pontos simulados simulando o leito das ruas
        np.random.seed(42)
        pontos_demanda = []
        # Força o alinhamento em eixos lineares (simulando ruas retas dentro da quadra)
        for _ in range(35):
            linearidade = np.random.choice([0, 1])
            if linearidade == 0:
                lat_rua = np.random.uniform(min(lats), max(lats))
                pontos_demanda.append([lat_rua, np.random.uniform(min(lngs), max(lngs))])
            else:
                lng_rua = np.random.uniform(min(lngs), max(lngs))
                pontos_demanda.append([np.random.uniform(min(lats), max(lats)), lng_rua])

        clientes_matriz = np.array(pontos_demanda)
        num_clientes = len(clientes_matriz)

        # Define quantidade de CTOs (Ajustado para o teto de até 6 CTOs por cabo de distribuição)
        capacidade_cto = int(dados.splitter_cto.split('x')[1])
        n_ctos_calculado = max(2, int(np.ceil(num_clientes / capacidade_cto)))
        n_ctos_calculado = min(n_ctos_calculado, 12) 

        kmeans_cto = KMeans(n_clusters=n_ctos_calculado, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        ctos_geometria = kmeans_cto.cluster_centers_

        # CEO centralizada
        ceo_coord = np.mean(ctos_geometria, axis=0)
        num_ctos_geradas = len(ctos_geometria)

        # Divide as CTOs em "Rotas/Ruas Lineares" de no máximo 6 caixas cada
        qtd_cabos_distribuicao = max(1, int(np.ceil(num_ctos_geradas / 6)))
        
        if qtd_cabos_distribuicao > 1:
            angulos = np.array([np.arctan2(c[0] - ceo_coord[0], c[1] - ceo_coord[1]) for c in ctos_geometria])
            kmeans_rotas = KMeans(n_clusters=qtd_cabos_distribuicao, random_state=42, n_init=10)
            kmeans_rotas.fit(angulos.reshape(-1, 1))
            labels_rotas = kmeans_rotas.labels_
        else:
            labels_rotas = np.zeros(num_ctos_geradas, dtype=int)

        kml = simplekml.Kml(name="Projeto FTTH - Sangria ASU 6FO")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABO DISTRIBUIÇÃO 6FO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)
        dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32

        # Cabo Tronco
        lin_tronco = fol_backbone.newlinestring(name="Cabo Tronco")
        lin_tronco.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(ceo_coord[1]), float(ceo_coord[0]))]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff"

        response_ctos = []
        html_ceo_tabela = ""

        # Montagem dos cabos sequenciais de 6FO
        for cabo_idx in range(qtd_cabos_distribuicao):
            indices_do_cabo = [idx for idx, lbl in enumerate(labels_rotas) if int(lbl) == cabo_idx]
            if not indices_do_cabo: continue

            coords_do_cabo = ctos_geometria[indices_do_cabo]
            # Ordena sequencialmente em linha (uma após a outra na rua) afastando-se da CEO
            dist_ceo = [np.linalg.norm(c - ceo_coord) for c in coords_do_cabo]
            ordem_rua = np.argsort(dist_ceo)

            pt_anterior = ceo_coord
            dist_acumulada = 0.0

            html_ceo_tabela += f"<h5>Cabo de Distribuição 0{cabo_idx+1} (6FO)</h5><table border='1' cellpadding='3' style='font-size:10px; border-collapse:collapse; width:100%;'>"
            
            for seq_pos, o_idx in enumerate(ordem_rua):
                if seq_pos >= 6: break # Teto limite de 6 caixas por cabo de 6 fibras
                
                real_c = coords_do_cabo[o_idx]
                c_id = indices_do_cabo[o_idx] + 1
                cor_fibra_ativa = CORES_ANATEL[seq_pos]

                d_trecho = np.sqrt((real_c[0]-pt_anterior[0])**2 + (real_c[1]-pt_anterior[1])**2) * 111.32
                dist_acumulada += d_trecho
                d_total = dist_olt_ceo + dist_acumulada
                potencia = dados.potencia_olt - ((d_total * 0.35) + perda_ceo + perda_cto + 0.6)

                # Documentação da CTO - Detalhando a sangria da fibra específica
                html_cto = f"""
                <div style="font-family:sans-serif; width:280px;">
                    <h3 style="background-color:#059669; color:white; padding:6px; margin:0;">📦 CTO {c_id:02d} (Sangrada)</h3>
                    <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                        <p><b>Identificação do Cabo:</b> Distribuição 0{cabo_idx+1} (6FO)</p>
                        <p><b>Posição na Linha:</b> {seq_pos+1}ª Caixa da Rua</p>
                        <p style="color:#2563eb; font-weight:bold;">✂️ Sangria na Linha: Fibra 0{seq_pos+1} ({cor_fibra_ativa}) -> Ativa</p>
                        <p style="color:#666;">Fibras restantes seguem passantes no tubo loose.</p>
                        <hr>
                        <p><b>Sinal na Caixa:</b> <b>{potencia:.2f} dBm</b></p>
                    </div>
                </div>
                """
                pnt = fol_ctos_root.newpoint(name=f"CTO {c_id:02d}", coords=[(float(real_c[1]), float(real_c[0]))])
                pnt.description = html_cto

                # LINHA EM BARRAMENTO CONTINUO: Liga na caixa anterior da mesma rua, e não de volta na CEO
                lin_cabo = fol_cabos_root.newlinestring(name=f"Cabo 0{cabo_idx+1} 6FO - Seção {seq_pos+1}")
                lin_cabo.coords = [(float(pt_anterior[1]), float(pt_anterior[0])), (float(real_c[1]), float(real_c[0]))]
                lin_cabo.style.linestyle.width = 3
                lin_cabo.style.linestyle.color = "ff00ff00"

                html_ceo_tabela += f"<tr><td>Porta {seq_pos+1}</td><td>Fundida na Fibra 0{seq_pos+1} ({cor_fibra_ativa})</td><td>➡️ Vai para CTO {c_id:02d}</td></tr>"

                response_ctos.append({
                    "id": c_id, "ceo_pai_id": 1,
                    "lat": float(real_c[0]), "lng": float(real_c[1]),
                    "potencia_dbm": float(round(potencia, 2)), "status": "ÓTIMO"
                })
                pt_anterior = real_c
                
            html_ceo_tabela += "</table><br>"

        # Atualiza a descrição unifilar da CEO
        html_ceo_completo = f"""
        <div style="font-family:sans-serif; width:340px;">
            <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0;">📋 UNIFILAR DE EMENDA - CEO 01</h3>
            <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                <p><b>Splitter 1º Nível:</b> {dados.splitter_ceo}</p>
                <p><b>Alimentação Tronco:</b> Fibra 01 (Verde) ➡️ Entrada IN do Splitter</p>
                <hr style="margin:8px 0;">
                {html_ceo_tabela}
            </div>
        </div>
        """
        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
        pnt_ceo.description = html_ceo_completo

        return {
            "status": "sucesso",
            "ceos": [{"id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)}],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no motor de sangria: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

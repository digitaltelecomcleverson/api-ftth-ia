import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH - Polígono e Unifilar")

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

class RequestProjetoPoligono(BaseModel):
    olt: Coordenada
    poligono: List[Coordenada]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor de Polígono e Unifilar Online"}

@app.post("/api/v1/calcular")
async def calcular_rede_poligono(dados: RequestProjetoPoligono):
    if len(dados.poligono) < 3:
        raise HTTPException(status_code=400, detail="Demarque uma área válida com o polígono.")

    try:
        # Extrai os limites do polígono para criar a malha de clientes da área
        lats = [pt.lat for pt in dados.poligono]
        lngs = [pt.lng for pt in dados.poligono]
        
        # Gera uma densidade urbana automatizada dentro do perímetro desenhado
        np.random.seed(42)
        pontos_demanda = []
        for _ in range(45):  # Simula 45 pontos de demanda/assinantes bem distribuídos
            pontos_demanda.append([np.random.uniform(min(lats), max(lats)), np.random.uniform(min(lngs), max(lngs))])
            
        clientes_matriz = np.array(pontos_demanda)
        num_clientes = len(clientes_matriz)

        # Define quantidade ideal de CTOs com base no splitter de atendimento
        capacidade_cto = int(dados.splitter_cto.split('x')[1])
        n_ctos_calculado = max(2, int(np.ceil(num_clientes / capacidade_cto)))
        n_ctos_calculado = min(n_ctos_calculado, 12) # Teto seguro por ramal PON

        # IA calcula os pontos ótimos para fixar as CTOs
        kmeans_cto = KMeans(n_clusters=n_ctos_calculado, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        ctos_geometria = kmeans_cto.cluster_centers_

        # Define o ponto central para a Caixa de Emenda (CEO)
        ceo_coord = np.mean(ctos_geometria, axis=0)
        
        kml = simplekml.Kml(name="Projeto Georreferenciado por Polígono")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Tronco)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)
        dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32

        # -----------------------------------------------------------------
        # DOCUMENTAÇÃO UNIFILAR EM HTML NA CEO (Para o Google Earth)
        # -----------------------------------------------------------------
        html_ceo = f"""
        <div style="font-family:sans-serif; width:340px; color:#333;">
            <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0; font-size:14px;">📋 UNIFILAR DE FUSÃO - CEO 01</h3>
            <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                <p><b>Splitter 1º Nível:</b> {dados.splitter_ceo}</p>
                <p style="color:#16a34a; font-weight:bold;">🟢 Alimentação: Fibra 01 (Verde) do Tronco ➡️ Porta IN</p>
                <hr style="border:0; border-top:1px solid #eee; margin:8px 0;">
                <table border="1" cellpadding="4" cellspacing="0" style="width:100%; border-collapse:collapse; font-size:11px;">
                    <tr style="background:#f3f4f6; font-weight:bold;"><th>Porta Saída</th><th>Fusão Tubo/Fibra</th><th>Destino Caixa</th></tr>
        """

        for i in range(len(ctos_geometria)):
            cor_f = CORES_ANATEL[i % len(CORES_ANATEL)]
            html_ceo += f"<tr><td>Porta 0{i+1}</td><td>Fibra 01 ({cor_f})</td><td>➡️ Distribuição CTO {i+1:02d}</td></tr>"
        
        html_ceo += "</table></div></div>"

        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
        pnt_ceo.description = html_ceo

        # Desenha cabo tronco
        lin_tronco = fol_backbone.newlinestring(name="Cabo Tronco Alimentador")
        lin_tronco.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(ceo_coord[1]), float(ceo_coord[0]))]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff"

        response_ctos = []

        # Distribuição Estrela Pura para evitar que os cabos façam laços ou voltas nas quadras
        for idx, cto_coord in enumerate(ctos_geometria):
            cto_id_num = int(idx + 1)
            cor_fibra_cto = CORES_ANATEL[idx % len(CORES_ANATEL)]

            dist_trecho = np.sqrt((cto_coord[0] - ceo_coord[0])**2 + (cto_coord[1] - ceo_coord[1])**2) * 111.32
            dist_total = dist_olt_ceo + dist_trecho
            potencia = dados.potencia_olt - ((dist_total * 0.35) + perda_ceo + perda_cto + 0.6)

            html_cto = f"""
            <div style="font-family:sans-serif; width:280px; color:#333;">
                <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 DOCUMENTAÇÃO - CTO {cto_id_num:02d}</h3>
                <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                    <p><b>Origem:</b> Saída Porta 0{cto_id_num} da CEO 01</p>
                    <p><b>Fibra Ativa no Atendimento:</b> Fibra {cto_id_num} ({cor_fibra_cto})</p>
                    <p><b>Splitter Interno:</b> {dados.splitter_cto}</p>
                    <p><b>Sinal Calculado:</b> <span style="color:#16a34a; font-weight:bold;">{potencia:.2f} dBm</span></p>
                </div>
            </div>
            """

            pnt = fol_ctos_root.newpoint(name=f"CTO {cto_id_num:02d}", coords=[(float(cto_coord[1]), float(cto_coord[0]))])
            pnt.description = html_cto

            # Linha direta dedicada ligando a CEO até a CTO
            lin = fol_cabos_root.newlinestring(name=f"Cabo Distribuição -> CTO {cto_id_num:02d}")
            lin.coords = [(float(ceo_coord[1]), float(ceo_coord[0])), (float(cto_coord[1]), float(cto_coord[0]))]
            lin.style.linestyle.width = 3
            lin.style.linestyle.color = "ff00ff00"

            response_ctos.append({
                "id": cto_id_num, "ceo_pai_id": 1,
                "lat": float(cto_coord[0]), "lng": float(cto_coord[1]),
                "potencia_dbm": float(round(potencia, 2)), "status": "ÓTIMO"
            })

        return {
            "status": "sucesso",
            "ceos": [{"id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)}],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no motor geométrico: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH Avançado - Customizável")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tabela oficial de perda de inserção teórica/prática dos splitters (dB)
TABELA_SPLITTERS = {
    "1x2": 3.8,
    "1x4": 7.2,
    "1x8": 10.5,
    "1x16": 13.8,
    "1x32": 17.0
}

class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjeto(BaseModel):
    olt: Coordenada
    clientes: List[Coordenada]
    n_ctos: int          # Garanta que está como int
    splitter_ceo: str    # Garanta que está como str
    splitter_cto: str    # Garanta que está como str
    potencia_olt: float  # Garanta que está como float

@app.get("/")
def read_root():
    return {"status": "Servidor FTTH Online"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    if not dados.clientes or len(dados.clientes) < dados.n_ctos:
        raise HTTPException(status_code=400, detail="Adicione mais clientes no mapa para calcular o agrupamento.")
    
    # Valida se os splitters escolhidos existem na nossa tabela de atenuação
    if dados.splitter_ceo not in TABELA_SPLITTERS or dados.splitter_cto not in TABELA_SPLITTERS:
        raise HTTPException(status_code=400, detail="Splitter selecionado inválido.")

    try:
        clientes_matriz = np.array([[c.lat, c.lng] for c in dados.clientes])
        
        # 1. IA - Nível 2: Posiciona as CTOs com base nos clientes
        kmeans_cto = KMeans(n_clusters=dados.n_ctos, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        ctos_geometria = kmeans_cto.cluster_centers_
        
        # 2. IA - Nível 1: Define a quantidade e posição das CEOs (Caixas de Emenda)
        # A quantidade de saídas do splitter da CEO dita quantas CTOs ela consegue agrupar
        capacidade_ceo = int(dados.splitter_ceo.split('x')[1]) 
        n_ceos = max(1, int(np.ceil(dados.n_ctos / capacidade_ceo)))
        
        kmeans_ceo = KMeans(n_clusters=n_ceos, random_state=42, n_init=10)
        kmeans_ceo.fit(ctos_geometria)
        ceos_geometria = kmeans_ceo.cluster_centers_
        labels_cto_para_ceo = kmeans_ceo.labels_
        
        # 3. Inicializa o arquivo KML
        kml = simplekml.Kml(name="Projeto FTTH Customizado")
        
        perda_ceo = TABELA_SPLITTERS[dados.splitter_ceo]
        perda_cto = TABELA_SPLITTERS[dados.splitter_cto]

        response_ceos = []
        for idx_ceo, ceo_coord in enumerate(ceos_geometria):
            dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32
            
            ponto_ceo = kml.newpoint(name=f"CEO {idx_ceo+1:02d} ({dados.splitter_ceo})", coords=[(ceo_coord[1], ceo_coord[0])])
            ponto_ceo.description = f"Caixa de Emenda de 1º Nível"
            
            cabo_tronco = kml.newlinestring(name=f"Cabo Tronco -> CEO {idx_ceo+1:02d}")
            cabo_tronco.coords = [(dados.olt.lng, dados.olt.lat), (ceo_coord[1], ceo_coord[0])]
            cabo_tronco.style.linestyle.width = 4
            cabo_tronco.style.linestyle.color = "ff0000ff" # Vermelho

            response_ceos.append({
                "id": idx_ceo + 1,
                "lat": float(ceo_coord[0]),
                "lng": float(ceo_coord[1]),
                "dist_olt_km": round(dist_olt_ceo, 2)
            })

        response_ctos = []
        for idx_cto, cto_coord in enumerate(ctos_geometria):
            id_ceo_vinculada = int(labels_cto_para_ceo[idx_cto])
            ceo_vinculada_coord = ceos_geometria[id_ceo_vinculada]
            
            dist_olt_ceo = np.sqrt((ceo_vinculada_coord[0] - dados.olt.lat)**2 + (ceo_vinculada_coord[1] - dados.olt.lng)**2) * 111.32
            dist_ceo_cto = np.sqrt((cto_coord[0] - ceo_vinculada_coord[0])**2 + (cto_coord[1] - ceo_vinculada_coord[1])**2) * 111.32
            distancia_total_fibra = dist_olt_ceo + dist_ceo_cto
            
            # Cálculo de Potência Dinâmico baseado nas escolhas do usuário
            perda_fibra = distancia_total_fibra * 0.35
            perda_total = perda_fibra + perda_ceo + perda_cto + 0.6  # 0.6dB margem de conexões/fusões
            potencia_final = dados.potencia_olt - perda_total
            status_sinal = "ÓTIMO" if potencia_final >= -25.0 else "SINAL FRACO"

            ponto_cto = kml.newpoint(name=f"CTO {idx_cto+1:02d} ({dados.splitter_cto})", coords=[(cto_coord[1], cto_coord[0])])
            
            cabo_dist = kml.newlinestring(name=f"Cabo Dist -> CTO {idx_cto+1:02d}")
            cabo_dist.coords = [(ceo_vinculada_coord[1], ceo_vinculada_coord[0]), (cto_coord[1], cto_coord[0])]
            cabo_dist.style.linestyle.width = 2
            cabo_dist.style.linestyle.color = "ff00ff00" # Verde

            response_ctos.append({
                "id": idx_cto + 1,
                "ceo_pai_id": id_ceo_vinculada + 1,
                "lat": float(cto_coord[0]),
                "lng": float(cto_coord[1]),
                "dist_total_km": round(distancia_total_fibra, 2),
                "potencia_dbm": round(potencia_final, 2),
                "status": status_sinal
            })
            
        return {
            "status": "sucesso",
            "ceos": response_ceos,
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

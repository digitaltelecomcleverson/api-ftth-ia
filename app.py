import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Dois Níveis")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjeto(BaseModel):
    olt: Coordenada
    clientes: List[Coordenada]
    n_ctos: int
    potencia_olt: float = 4.0

@app.get("/")
def read_root():
    return {"status": "Servidor FTTH Online"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    if not dados.clientes or len(dados.clientes) < dados.n_ctos:
        raise HTTPException(status_code=400, detail="Adicione mais clientes para a clusterização em dois níveis.")
    
    try:
        clientes_matriz = np.array([[c.lat, c.lng] for c in dados.clientes])
        
        # 1. IA - Nível 2: Agrupa clientes para encontrar a posição ideal das CTOs de Atendimento
        kmeans_cto = KMeans(n_clusters=dados.n_ctos, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        ctos_geometria = kmeans_cto.cluster_centers()
        
        # 2. IA - Nível 1: Agrupa as CTOs criadas para encontrar o local ideal da CEO (Caixa de Emenda)
        # Define 1 CEO para cada 4 ou 8 CTOs (relação padrão de mercado)
        n_ceos = max(1, int(np.ceil(dados.n_ctos / 4)))
        kmeans_ceo = KMeans(n_clusters=n_ceos, random_state=42, n_init=10)
        kmeans_ceo.fit(ctos_geometria)
        ceos_geometria = kmeans_ceo.cluster_centers()
        labels_cto_para_ceo = kmeans_ceo.labels_
        
        # 3. Inicializa o arquivo do Google Earth (KML)
        kml = simplekml.Kml(name="Projeto FTTH IA - Dois Níveis")
        
        response_ceos = []
        response_ctos = []

        # Criar as CEOs (1º Nível) no JSON e KML
        for idx_ceo, ceo_coord in enumerate(ceos_geometria):
            dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32
            
            # Marcador da CEO
            ponto_ceo = kml.newpoint(name=f"CEO {idx_ceo+1:02d} (Splitter 1:4)", coords=[(ceo_coord[1], ceo_coord[0])])
            ponto_ceo.description = f"Caixa de Emenda\nDistância da OLT: {dist_olt_ceo:.2f} km"
            
            # Cabo Tronco (Alimentador): OLT -> CEO
            cabo_tronco = kml.newlinestring(name=f"Cabo Tronco -> CEO {idx_ceo+1:02d}")
            cabo_tronco.coords = [(dados.olt.lng, dados.olt.lat), (ceo_coord[1], ceo_coord[0])]
            cabo_tronco.style.linestyle.width = 4
            cabo_tronco.style.linestyle.color = "ff0000ff" # Vermelho no KML

            response_ceos.append({
                "id": idx_ceo + 1,
                "lat": float(ceo_coord[0]),
                "lng": float(ceo_coord[1]),
                "dist_olt_km": round(dist_olt_ceo, 2)
            })

        # Criar as CTOs (2º Nível) vinculadas às suas respectivas CEOs
        for idx_cto, cto_coord in enumerate(ctos_geometria):
            id_ceo_vinculada = int(labels_cto_para_ceo[idx_cto])
            ceo_vinculada_coord = ceos_geometria[id_ceo_vinculada]
            
            # Distâncias do caminho da luz (OLT -> CEO -> CTO)
            dist_olt_ceo = np.sqrt((ceo_vinculada_coord[0] - dados.olt.lat)**2 + (ceo_vinculada_coord[1] - dados.olt.lng)**2) * 111.32
            dist_ceo_cto = np.sqrt((cto_coord[0] - ceo_vinculada_coord[0])**2 + (cto_coord[1] - ceo_vinculada_coord[1])**2) * 111.32
            distancia_total_fibra = dist_olt_ceo + dist_ceo_cto
            
            # Orçamento de potência de 2 Níveis: 
            # Perda Fibra + Fusões + Splitter 1º Nível (1x4 = ~7.2dB) + Splitter 2º Nível (1x8 = ~10.5dB)
            perda_fibra = distancia_total_fibra * 0.35
            perda_splitters = 7.2 + 10.5
            perda_conexoes = 0.6
            perda_total = perda_fibra + perda_splitters + perda_conexoes
            potencia_final = dados.potencia_olt - perda_total
            
            status_sinal = "ÓTIMO" if potencia_final >= -25.0 else "SINAL FRACO"

            # Marcador da CTO no KML
            ponto_cto = kml.newpoint(name=f"CTO {idx_cto+1:02d} (Splitter 1:8)", coords=[(cto_coord[1], cto_coord[0])])
            ponto_cto.description = f"Sinal: {potencia_final:.2f} dBm\nDistância Total: {distancia_total_fibra:.2f} km"
            
            # Cabo de Distribuição: CEO -> CTO
            cabo_dist = kml.newlinestring(name=f"Cabo Dist -> CTO {idx_cto+1:02d}")
            cabo_dist.coords = [(ceo_vinculada_coord[1], ceo_vinculada_coord[0]), (cto_coord[1], cto_coord[0])]
            cabo_dist.style.linestyle.width = 2
            cabo_dist.style.linestyle.color = "ff00ff00" # Verde no KML

            response_ctos.append({
                "id": idx_cto + 1,
                "ceo_pai_id": id_ceo_vinculada + 1,
                "lat": float(cto_coord[0]),
                "lng": float(cto_coord[1]),
                "dist_total_km": round(distancia_total_fibra, 2),
                "potencia_dbm": round(potencia_final, 2),
                "status": status_sinal
            })
            
        kml_string = kml.kml()

        return {
            "status": "sucesso",
            "ceos": response_ceos,
            "ctos": response_ctos,
            "kml_conteudo": kml_string
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

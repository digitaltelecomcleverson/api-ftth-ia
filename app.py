import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Topologia de Ramal e Pastas Estruturadas")

# Configuração de CORS para permitir que o seu site na Vercel acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tabela oficial de perda de inserção teórica/prática dos splitters (em dB)
TABELA_SPLITTERS = {
    "1x2": 3.8,
    "1x4": 7.2,
    "1x8": 10.5,
    "1x16": 13.8,
    "1x32": 17.0
}

# Modelos de dados para validação da requisição (Pydantic)
class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjeto(BaseModel):
    olt: Coordenada
    clientes: List[Coordenada]
    n_ctos: int
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Servidor FTTH Online"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    if not dados.clientes or len(dados.clientes) < dados.n_ctos:
        raise HTTPException(status_code=400, detail="Adicione mais clientes no mapa para permitir o agrupamento da IA.")
    
    if dados.splitter_ceo not in TABELA_SPLITTERS or dados.splitter_cto not in TABELA_SPLITTERS:
        raise HTTPException(status_code=400, detail="Splitter selecionado inválido.")

    try:
        # Converte a lista de clientes para uma matriz NumPy para processamento matemático
        clientes_matriz = np.array([[c.lat, c.lng] for c in dados.clientes])
        
        # 1. IA - Nível 2: Clusterização para encontrar as posições ideais das CTOs
        kmeans_cto = KMeans(n_clusters=dados.n_ctos, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        ctos_geometria = kmeans_cto.cluster_centers()
        
        # 2. IA - Nível 1: Define a quantidade e posições ideais das CEOs (Caixas de Emenda)
        capacidade_ceo = int(dados.splitter_ceo.split('x')[1]) 
        n_ceos = max(1, int(np.ceil(dados.n_ctos / capacidade_ceo)))
        
        kmeans_ceo = KMeans(n_clusters=n_ceos, random_state=42, n_init=10)
        kmeans_ceo.fit(ctos_geometria)
        ceos_geometria = kmeans_ceo.cluster_centers()
        labels_cto_para_ceo = kmeans_ceo.labels_
        
        # 3. Inicializa o arquivo do Google Earth (KML)
        kml = simplekml.Kml(name="Projeto FTTH IA - Estruturado")
        
        # Criando a árvore estruturada de pastas profissionais exigida pelo provedor
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Tronco)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO (Ramais)")

        perda_ceo = TABELA_SPLITTERS[dados.splitter_ceo]
        perda_cto = TABELA_SPLITTERS[dados.splitter_cto]

        response_ceos = []
        # Processamento e desenho das Caixas de Emenda (CEOs) e Cabos Tronco
        for i, coord in enumerate(ceos_geometria):
            ceo_id = int(i + 1)
            dist_olt_ceo = np.sqrt((coord[0] - dados.olt.lat)**2 + (coord[1] - dados.olt.lng)**2) * 111.32
            
            # Adiciona pino da CEO na pasta correta do KML
            pnt = fol_ceos.newpoint(name=f"CEO {ceo_id:02d} ({dados.splitter_ceo})", coords=[(coord[1], coord[0])])
            pnt.description = f"Caixa de Emenda de 1º Nível\nDistância da OLT: {dist_olt_ceo:.2f} km"
            
            # Adiciona Cabo Tronco (Backbone) interligando a OLT até a CEO
            lin = fol_backbone.newlinestring(name=f"Backbone -> CEO {ceo_id:02d}")
            lin.coords = [(dados.olt.lng, dados.olt.lat), (coord[1], coord[0])]
            lin.style.linestyle.width = 5
            lin.style.linestyle.color = "ff0000ff" # Vermelho no Google Earth

            response_ceos.append({
                "id": ceo_id,
                "lat": float(coord[0]),
                "lng": float(coord[1]),
                "dist_olt_km": round(dist_olt_ceo, 2)
            })

        response_ctos = []
        # Processamento das CTOs organizadas por Ramais Sequenciais (Topologia de Barramento)
        for i_ceo in range(n_ceos):
            ceo_id_atual = int(i_ceo + 1)
            indices_ctos_deste_ramal = [idx for idx, label in enumerate(labels_cto_para_ceo) if label == i_ceo]
            
            if not indices_ctos_deste_ramal:
                continue

            # Cria subpastas organizadas para cada Ramal PON dentro do KML
            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal {ceo_id_atual:02d} - CTOs")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabo Ramal {ceo_id_atual:02d}")
            
            coords_ctos_ramal = ctos_geometria[indices_ctos_deste_ramal]
            ceo_coord = ceos_geometria[i_ceo]
            
            # Algoritmo de Rota inteligente (Vizinho Mais Próximo): CEO -> CTO 1 -> CTO 2 -> CTO 3...
            ponto_atual = ceo_coord
            restantes = list(zip(indices_ctos_deste_ramal, coords_ctos_ramal))
            sequencia_rota = []
            
            while restantes:
                mais_proxima = min(restantes, key=lambda x: np.linalg.norm(x[1] - ponto_atual))
                sequencia_rota.append(mais_proxima)
                ponto_atual = mais_proxima[1]
                restantes.remove(mais_proxima)

            # Desenha as linhas físicas e calcula as potências acumuladas do barramento
            ponto_anterior = ceo_coord
            dist_acumulada_ramal = 0.0
            
            for idx_seq, (real_idx, cto_coord) in enumerate(sequencia_rota):
                cto_id_num = int(real_idx + 1)
                
                # Distância do trecho atual do cabo
                dist_trecho = np.sqrt((cto_coord[0] - ponto_anterior[0])**2 + (cto_coord[1] - ponto_anterior[1])**2) * 111.32
                dist_acumulada_ramal += dist_trecho
                
                # Distância total percorrida pela luz desde a OLT passando pela CEO e ramal
                dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32
                dist_total_fibra = dist_olt_ceo + dist_acumulada_ramal
                
                # Orçamento de potência real de 2 níveis
                perda_fibra = dist_total_fibra * 0.35 # 0.35 dB por km
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.8 # 0.8 dB de margem para fusões/conectores
                potencia_final = dados.potencia_olt - perda_total
                
                # Adiciona o marcador da CTO na subpasta correspondente do KML
                pnt = fol_ramal_cto.newpoint(name=f"CTO {cto_id_num:02d} ({dados.splitter_cto})", coords=[(cto_coord[1], cto_coord[0])])
                pnt.description = f"Potência de Sinal: {potencia_final:.2f} dBm\nDistância Total: {dist_total_fibra:.2f} km\nVinculada à CEO: {ceo_id_atual:02d}"
                
                # Desenha o cabo de distribuição interligando em cascata/barramento
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Trecho: CTO {cto_id_num:02d}")
                lin.coords = [(ponto_anterior[1], ponto_anterior[0]), (cto_coord[1], cto_coord[0])]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00" # Verde no Google Earth
                
                response_ctos.append({
                    "id": cto_id_num,
                    "ceo_pai_id": ceo_id_atual,
                    "lat": float(cto_coord[0]),
                    "lng": float(cto_coord[1]),
                    "potencia_dbm": float(round(potencia_final, 2)),
                    "status": "ÓTIMO" if potencia_final >= -25.0 else "SINAL FRACO"
                })
                # O ponto atual vira o ponto de partida para a próxima CTO do ramal
                ponto_anterior = cto_coord

        return {
            "status": "sucesso",
            "ceos": response_ceos,
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
        
    except Exception as e:
        print(f"ERRO CRÍTICO NO PROCESSAMENTO DA REDE: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro interno no motor de cálculo: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

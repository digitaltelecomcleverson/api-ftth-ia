import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Vetores Lineares de Direção")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {
    "1x2": 3.8,
    "1x4": 7.2,
    "1x8": 10.5,
    "1x16": 13.8,
    "1x32": 17.0
}

CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta", "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"]

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
    return {"status": "Motor FTTH Vetorial Linear Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    if not dados.clientes:
        raise HTTPException(status_code=400, detail="Adicione clientes no mapa.")

    try:
        clientes_matriz = np.array([[float(c.lat), float(c.lng)] for c in dados.clientes], dtype=float)
        num_clientes = len(clientes_matriz)
        
        n_clusters_cto = min(int(dados.n_ctos), num_clientes)
        if n_clusters_cto < 1: n_clusters_cto = 1

        if num_clientes <= n_clusters_cto or num_clientes == 1:
            ctos_geometria = clientes_matriz
        else:
            kmeans_cto = KMeans(n_clusters=n_clusters_cto, random_state=42, n_init=10)
            kmeans_cto.fit(clientes_matriz)
            ctos_geometria = kmeans_cto.cluster_centers_

        num_ctos_geradas = len(ctos_geometria)
        
        # 1. A CEO é posicionada no centro de gravidade geográfico das CTOs
        ceo_coord = np.mean(ctos_geometria, axis=0)
        
        # 2. Em vez de usar KMeans para os ramais, calculamos o ÂNGULO de cada CTO em relação à CEO.
        # Isso separa as CTOs por direções reais (ex: Lado Esquerdo da rua vs Lado Direito da rua)
        angulos = []
        for cto in ctos_geometria:
            dy = cto[0] - ceo_coord[0] # diferença latitude
            dx = cto[1] - ceo_coord[1] # diferença longitude
            angulo = np.arctan2(dy, dx)
            angulos.append(angulo)
        angulos = np.array(angulos)

        capacidade_ceo = int(dados.splitter_ceo.split('x')[1])
        qtd_ramais_saida = min(capacidade_ceo, num_ctos_geradas, 4) # Limita a até 4 direções principais (ex: Norte, Sul, Leste, Oeste)

        # Agrupa os ângulos para definir os lados reais da rua/bairro
        if qtd_ramais_saida > 1:
            kmeans_ang = KMeans(n_clusters=qtd_ramais_saida, random_state=42, n_init=10)
            kmeans_ang.fit(angulos.reshape(-1, 1))
            labels_ramais = kmeans_ang.labels_
        else:
            labels_ramais = np.zeros(num_ctos_geradas, dtype=int)

        kml = simplekml.Kml(name="Projeto FTTH - Ramais Lineares Diretos")
        
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)
        dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32

        # -----------------------------------------------------------------
        # DOCUMENTAÇÃO EM HTML DA CEO (DIAGRAMA DE EMENDA NO GOOGLE EARTH)
        # -----------------------------------------------------------------
        html_ceo = f"""
        <div style="font-family:sans-serif; width:340px; color:#333;">
            <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0; font-size:14px;">📋 DIAGRAMA DE FUSÃO - CEO 01</h3>
            <div style="padding:10px; border:1px solid #css; background:#fff; font-size:12px;">
                <p><b>Splitter de 1º Nível Primário:</b> {dados.splitter_ceo}</p>
                <p style="color:#16a34a; font-weight:bold;">🟢 Fusão de Entrada: Fibra 01 (Verde) do Cabo Tronco ➡️ Entrada IN do Splitter</p>
                <hr style="border:0; border-top:1px solid #eee; margin:8px 0;">
                <h4 style="margin:0 0 6px 0; color:#1e40af;">Organização de Saídas Ópticas (Fusão nos Cabos):</h4>
                <table border="1" cellpadding="5" cellspacing="0" style="width:100%; border-collapse:collapse; font-size:11px; text-align:left;">
                    <tr style="background:#f3f4f6; font-weight:bold;">
                        <th>Saída</th>
                        <th>Fusão Interna</th>
                        <th>Destino do Ramal</th>
                    </tr>
        """

        for i_ramal in range(qtd_ramais_saida):
            cor_f = CORES_ANATEL[i_ramal % len(CORES_ANATEL)]
            html_ceo += f"""
                    <tr>
                        <td><b>Porta 0{i_ramal+1}</b></td>
                        <td>Fibra 01 ({cor_f})</td>
                        <td>➡️ Cabo Lado {i_ramal+1} (Rua Linha Reta)</td>
                    </tr>
            """
        
        html_ceo += "</table></div></div>"

        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
        pnt_ceo.description = html_ceo
        
        lin_tronco = fol_backbone.newlinestring(name="Cabo Tronco Alimentador (OLT -> CEO)")
        lin_tronco.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(ceo_coord[1]), float(ceo_coord[0]))]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff" # Vermelho Forte para o Tronco

        response_ctos = []
        
        # -----------------------------------------------------------------
        # CONSTRUÇÃO DOS RAMAIS EM VETOR RETILÍNEO (LADOS DA RUA)
        # -----------------------------------------------------------------
        for i_ramal in range(qtd_ramais_saida):
            ramal_id = int(i_ramal + 1)
            cor_fibra_ramal = CORES_ANATEL[i_ramal % len(CORES_ANATEL)]
            
            # Filtra apenas as CTOs pertencentes a este vetor direcional específico
            indices_deste_ramal = [idx for idx, lbl in enumerate(labels_ramais) if int(lbl) == i_ramal]
            if not indices_deste_ramal:
                continue

            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal Lado {ramal_id} - Caixas")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabo Distribuição - Lado {ramal_id}")
            
            coords_ctos_ramal = ctos_geometria[indices_deste_ramal]
            ids_ctos_ramal = indices_deste_ramal
            
            # ORDENAÇÃO VETORIAL ESTRELA: Mede a distância direta de cada caixa a partir da CEO. 
            # Isso força o cabo a seguir em linha reta para fora, sem voltar para trás ou cruzar quarteirões.
            distancias_da_ceo = [np.linalg.norm(cto - ceo_coord) for cto in coords_ctos_ramal]
            ordenacao_linear = np.argsort(distancias_da_ceo)
            
            ponto_anterior = ceo_coord
            dist_acumulada_ramal = 0.0
            
            for seq_idx, idx_ordenado in enumerate(ordenacao_linear):
                real_idx = ids_ctos_ramal[idx_ordenado]
                cto_coord = coords_ctos_ramal[idx_ordenado]
                cto_id_num = int(real_idx + 1)
                
                dist_trecho = np.sqrt((cto_coord[0] - ponto_anterior[0])**2 + (cto_coord[1] - ponto_anterior[1])**2) * 111.32
                dist_acumulada_ramal += dist_trecho
                
                dist_total_fibra = dist_olt_ceo + dist_acumulada_ramal
                perda_fibra = dist_total_fibra * 0.35
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.6
                potencia_final = dados.potencia_olt - perda_total
                
                # -----------------------------------------------------------------
                # DOCUMENTAÇÃO EM HTML DA CTO (BALÃO INTERNO NO GOOGLE EARTH)
                # -----------------------------------------------------------------
                html_cto = f"""
                <div style="font-family:sans-serif; width:300px; color:#333;">
                    <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0; font-size:13px;">📦 DETALHES TÉCNICOS - CTO {cto_id_num:02d}</h3>
                    <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                        <p><b>Ramal Distribuidor:</b> Cabo Linear Lado {ramal_id}</p>
                        <p><b>Fibra Designada na CEO:</b> Fibra Ativa 01 ({cor_fibra_ramal})</p>
                        <p><b>Atendimento da Caixa:</b> Splitter 2º Nível {dados.splitter_cto}</p>
                        <p><b>Distância Total da Fibra (da OLT):</b> {dist_total_fibra:.2f} km</p>
                        <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                        <p style="margin:0; font-size:13px;"><b>Potência Calculada:</b> <span style="color:#16a34a; font-weight:bold;">{potencia_final:.2f} dBm</span></p>
                    </div>
                </div>
                """

                pnt = fol_ramal_cto.newpoint(name=f"CTO {cto_id_num:02d}", coords=[(float(cto_coord[1]), float(cto_coord[0]))])
                pnt.description = html_cto
                
                # Plota a linha retilínea sequencial perfeita ligando os postes
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Distribuição Lado {ramal_id} - Seção {seq_idx+1}")
                lin.coords = [(float(ponto_anterior[1]), float(ponto_anterior[0])), (float(cto_coord[1]), float(cto_coord[0]))]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00" # Verde para Cabos de Atendimento
                
                response_ctos.append({
                    "id": cto_id_num,
                    "ceo_pai_id": 1,
                    "lat": float(cto_coord[0]),
                    "lng": float(cto_coord[1]),
                    "potencia_dbm": float(round(potencia_final, 2)),
                    "status": "ÓTIMO" if potencia_final >= -25.0 else "SINAL FRACO"
                })
                ponto_anterior = cto_coord

        return {
            "status": "sucesso",
            "ceos": [{"id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)}],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor vetorial: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

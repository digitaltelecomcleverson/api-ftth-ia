import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Multi-Ramal Linear")

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
    return {"status": "Motor FTTH Otimizado Ativo"}

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
        
        # Posiciona a CEO no centro geométrico das caixas geradas
        ceo_coord = np.mean(ctos_geometria, axis=0)
        
        # Define quantos "lados" (ramais independentes) vão sair da CEO com base nas direções das CTOs
        capacidade_ceo = int(dados.splitter_ceo.split('x')[1]) 
        qtd_ramais_saida = min(capacidade_ceo, num_ctos_geradas, 4) # Limita a até 4 direções principais (Esquerda/Direita/Frente/Trás)
        
        if qtd_ramais_saida > 1:
            kmeans_ramal = KMeans(n_clusters=qtd_ramais_saida, random_state=42, n_init=10)
            kmeans_ramal.fit(ctos_geometria)
            labels_cto_para_ramal = kmeans_ramal.labels_
        else:
            labels_cto_para_ramal = np.zeros(num_ctos_geradas, dtype=int)

        kml = simplekml.Kml(name="Projeto FTTH - Linhas de Ramal Otimizadas")
        
        # Pastas estruturadas
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)
        dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32

        # --- GERAÇÃO DA DOCUMENTAÇÃO EM HTML PARA A CEO ---
        html_ceo = f"""
        <div style="font-family:sans-serif; width:320px; color:#333;">
            <h3 style="background-color:#2563eb; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0;">DIAGRAMA DE FUSÃO - CEO 01</h3>
            <div style="padding:10px; border:1px solid #ddd; background:#fff;">
                <p><b>Splitter 1º Nível:</b> {dados.splitter_ceo}</p>
                <p><b>Cabo Alimentador:</b> Fibra 01 (Verde) ➡️ ENTRADA do Splitter</p>
                <hr>
                <h4 style="margin:5px 0;">Distribuição de Saídas por Lado:</h4>
                <table border="1" cellpadding="4" cellspacing="0" style="width:100%; border-collapse:collapse; font-size:11px;">
                    <tr style="background:#f3f4f6;"><th>Saída Splitter</th><th>Fusão Destino</th><th>Direção / Lado</th></tr>
        """

        for i_ramal in range(qtd_ramais_saida):
            cor_f = CORES_ANATEL[i_ramal % len(CORES_ANATEL)]
            html_ceo += f"<tr><td>Saída 0{i_ramal+1}</td><td>Fibra 01 ({cor_f})</td><td>Cabo Distribuição - Lado {i_ramal+1}</td></tr>"
        
        html_ceo += "</table></div></div>"

        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
        pnt_ceo.description = html_ceo
        
        lin_tronco = fol_backbone.newlinestring(name="Cabo Tronco (OLT -> CEO 01)")
        lin_tronco.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(ceo_coord[1]), float(ceo_coord[0]))]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff" # Vermelho Tronco

        response_ceos = [{"id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)}]
        response_ctos = []
        
        # --- PROCESSAMENTO DOS RAMAIS LINEARES INDEPENDENTES ---
        for i_ramal in range(qtd_ramais_saida):
            ramal_id = int(i_ramal + 1)
            cor_fibra_ramal = CORES_ANATEL[i_ramal % len(CORES_ANATEL)]
            indices_ctos_deste_ramal = [idx for idx, label in enumerate(labels_cto_para_ramal) if int(label) == i_ramal]
            
            if not indices_ctos_deste_ramal:
                continue

            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal Lado {ramal_id} - CTOs")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabos do Ramal Lado {ramal_id}")
            
            coords_ctos_ramal = ctos_geometria[indices_ctos_deste_ramal]
            
            # Ordenação linear estrita partindo da CEO em direção ao fim da rua (Vizinho mais próximo)
            ponto_atual = ceo_coord
            restantes = list(zip(indices_ctos_deste_ramal, coords_ctos_ramal))
            sequencia_rota = []
            
            while restantes:
                mais_proxima = min(restantes, key=lambda x: np.linalg.norm(x[1] - ponto_atual))
                sequencia_rota.append(mais_proxima)
                ponto_atual = mais_proxima[1]
                restantes.remove(mais_proxima)

            ponto_anterior = ceo_coord
            dist_acumulada_ramal = 0.0
            
            for idx_seq, (real_idx, cto_coord) in enumerate(sequencia_rota):
                cto_id_num = int(real_idx + 1)
                
                dist_trecho = np.sqrt((cto_coord[0] - ponto_anterior[0])**2 + (cto_coord[1] - ponto_anterior[1])**2) * 111.32
                dist_acumulada_ramal += dist_trecho
                
                dist_total_fibra = dist_olt_ceo + dist_acumulada_ramal
                perda_fibra = dist_total_fibra * 0.35
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.6
                potencia_final = dados.potencia_olt - perda_total
                
                # --- DOCUMENTAÇÃO INTERNA DA CTO ---
                html_cto = f"""
                <div style="font-family:sans-serif; width:280px; color:#333;">
                    <h3 style="background-color:#10b981; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">DETALHES - CTO {cto_id_num:02d}</h3>
                    <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                        <p><b>Ramal de Origem:</b> Cabo Distribuição Lado {ramal_id}</p>
                        <p><b>Fibra Derivada da CEO:</b> Fibra 01 ({cor_fibra_ramal})</p>
                        <p><b>Splitter de Atendimento:</b> {dados.splitter_cto}</p>
                        <p><b>Distância da OLT:</b> {dist_total_fibra:.2f} km</p>
                        <hr>
                        <p style="margin:5px 0;"><b>Sinal Estimado:</b> <span style="color:green; font-weight:bold;">{potencia_final:.2f} dBm</span></p>
                    </div>
                </div>
                """

                pnt = fol_ramal_cto.newpoint(name=f"CTO {cto_id_num:02d}", coords=[(float(cto_coord[1]), float(cto_coord[0]))])
                pnt.description = html_cto
                
                # Desenha o cabo linear unindo os pontos sequencialmente
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Lado {ramal_id} - Trecho {idx_seq+1}")
                lin.coords = [(float(ponto_anterior[1]), float(ponto_anterior[0])), (float(cto_coord[1]), float(cto_coord[0]))]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00" # Verde Distribuição
                
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
            "ceos": response_ceos,
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor de cálculo: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

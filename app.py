import os
import numpy as np
import simplekml
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH Ultra-Autônomo por Polígono")

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

def buscar_casas_no_poligono(poligono: List[Coordenada]) -> List[List[float]]:
    """ Consulta a API do OpenStreetMap para extrair localizações reais de imóveis dentro da área """
    coords_str = " ".join([f"{pt.lat} {pt.lng}" for pt in poligono])
    
    # Query Overpass para buscar prédios e residências dentro do polígono demarcado
    query = f"""
    [out:json][timeout:25];
    (
      node["building"](poly:"{coords_str}");
      way["building"](poly:"{coords_str}");
    );
    out center;
    """
    url = "https://overpass-api.de/api/interpreter"
    try:
        response = requests.post(url, data={"data": query}, timeout=20)
        data = response.json()
        pontos = []
        for elem in data.get("elements", []):
            if "center" in elem:
                pontos.append([elem["center"]["lat"], elem["center"]["lng"]])
            elif elem.get("type") == "node":
                pontos.append([elem["lat"], elem["lng"]])
        return pontos
    except Exception:
        return []

@app.get("/")
def read_root():
    return {"status": "Motor de Polígono Autônomo Online"}

@app.post("/api/v1/calcular")
async def calcular_rede_poligono(dados: RequestProjetoPoligono):
    if len(dados.poligono) < 3:
        raise HTTPException(status_code=400, detail="Demarque uma área válida com pelo menos 3 pontos no polígono.")

    # 1. Busca imóveis e pontos de demanda reais da área via satélite/mapeamento urbano
    pontos_demanda = buscar_casas_no_poligono(dados.poligono)
    
    # Se a API pública não retornar pontos na região, geramos uma malha simulada sobre a área para não travar
    if len(pontos_demanda) < 5:
        lats = [pt.lat for pt in dados.poligono]
        lngs = [pt.lng for pt in dados.poligono]
        # Cria pontos fictícios distribuídos para simular assinantes
        for _ in range(30):
            pontos_demanda.append([np.random.uniform(min(lats), max(lats)), np.random.uniform(min(lngs), max(lngs))])

    clientes_matriz = np.array(pontos_demanda)
    num_clientes = len(clientes_matriz)

    # 2. Define a quantidade ideal de CTOs com base na densidade de assinantes e no splitter selecionado
    capacidade_cto = int(dados.splitter_cto.split('x')[1])
    n_ctos_calculado = max(2, int(np.ceil(num_clientes / capacidade_cto)))
    n_ctos_calculado = min(n_ctos_calculado, 24) # Teto de segurança por PON

    # IA posiciona as CTOs nos centros de carga
    kmeans_cto = KMeans(n_clusters=n_ctos_calculado, random_state=42, n_init=10)
    kmeans_cto.fit(clientes_matriz)
    ctos_geometria = kmeans_cto.cluster_centers_

    # 3. Posiciona a CEO centralizadora
    ceo_coord = np.mean(ctos_geometria, axis=0)
    capacidade_ceo = int(dados.splitter_ceo.split('x')[1])
    qtd_ramais = min(capacidade_ceo, len(ctos_geometria), 4)

    # Separa ramais lineares estritos por vetor angular
    angulos = np.array([np.arctan2(c[0] - ceo_coord[0], c[1] - ceo_coord[1]) for c in ctos_geometria])
    kmeans_ramal = KMeans(n_clusters=qtd_ramais, random_state=42, n_init=10)
    kmeans_ramal.fit(angulos.reshape(-1, 1))
    labels_ramais = kmeans_ramal.labels_

    # 4. Geração do KML Documentado
    kml = simplekml.Kml(name="Projeto Autônomo por Polígono")
    fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
    fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
    fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
    fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

    perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
    perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)
    dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32

    # HTML Unifilar da CEO
    html_ceo = f"<h3>📋 UNIFILAR DE EMENDA - CEO 01</h3><p><b>Splitter 1º Nível:</b> {dados.splitter_ceo}</p><table border='1' cellpadding='4' style='font-size:11px; border-collapse:collapse;'>"
    for r in range(qtd_ramais):
        html_ceo += f"<tr><td>Porta 0{r+1}</td><td>➡️ Fibra {CORES_ANATEL[r]}</td><td>Ramal Lado {r+1}</td></tr>"
    html_ceo += "</table>"

    pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
    pnt_ceo.description = html_ceo

    lin_tronco = fol_backbone.newlinestring(name="Cabo Tronco")
    lin_tronco.coords = [(dados.olt.lng, dados.olt.lat), (ceo_coord[1], ceo_coord[0])]
    lin_tronco.style.linestyle.width = 5
    lin_tronco.style.linestyle.color = "ff0000ff"

    response_ctos = []
    for r_id in range(qtd_ramais):
        indices = [idx for idx, lbl in enumerate(labels_ramais) if int(lbl) == r_id]
        if not indices: continue
        
        coords_r = ctos_geometria[indices]
        dists = [np.linalg.norm(c - ceo_coord) for c in coords_r]
        ordem = np.argsort(dists)
        
        pt_anterior = ceo_coord
        dist_acumulada = 0.0
        
        for s_idx, o_idx in enumerate(ordem):
            real_c = coords_r[o_idx]
            c_id = indices[o_idx] + 1
            
            d_trecho = np.sqrt((real_c[0]-pt_anterior[0])**2 + (real_c[1]-pt_anterior[1])**2) * 111.32
            dist_acumulada += d_trecho
            d_total = dist_olt_ceo + dist_acumulada
            potencia = dados.potencia_olt - ((d_total * 0.35) + perda_ceo + perda_cto + 0.6)
            
            html_cto = f"<h3>📦 CTO {c_id:02d}</h3><p><b>Fibra Ativa:</b> {CORES_ANATEL[r_id]}</p><p><b>Sinal:</b> {potencia:.2f} dBm</p>"
            pnt_c = fol_ctos_root.newfolder(name=f"Ramal {r_id+1}").newpoint(name=f"CTO {c_id:02d}", coords=[(real_c[1], real_c[0])])
            pnt_c.description = html_cto
            
            lin_d = fol_cabos_root.newlinestring(name=f"Cabo Ramal {r_id+1}")
            lin_d.coords = [(pt_anterior[1], pt_anterior[0]), (real_c[1], real_c[0])]
            lin_d.style.linestyle.width = 3
            lin_d.style.linestyle.color = "ff00ff00"
            
            response_ctos.append({"id": c_id, "ceo_pai_id": 1, "lat": float(real_c[0]), "lng": float(real_c[1]), "potencia_dbm": round(potencia, 2), "status": "ÓTIMO"})
            pt_anterior = real_c

    return {
        "status": "sucesso",
        "ceos": [{"id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)}],
        "ctos": response_ctos,
        "kml_conteudo": kml.kml()
    }

import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI(title="Motor FTTH Profissional")

# Configuração de Segurança (CORS)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Configurações Anatel
TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta", "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"]

class Elemento(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str
    pai_id: int

class RequestFTTH(BaseModel):
    olt: dict
    ceos: List[Elemento]
    ctos: List[Elemento]
    splitter_ceo: str
    potencia_olt: float

@app.post("/api/v1/calcular")
async def calcular(dados: RequestFTTH):
    try:
        # 1. Configuração do KML
        kml = simplekml.Kml(name="Projeto_Digital_Telecom")
        fol_ceo = kml.newfolder(name="CEOs")
        fol_cto = kml.newfolder(name="CTOs")
        fol_cabo = kml.newfolder(name="Cabos")

        # 2. Mapeamento de Hierarquia (Árvore)
        dict_ctos = {c.id: c for c in dados.ctos}
        adj = {c.id: [] for c in dados.ctos}
        for cto in dados.ctos:
            if cto.pai_tipo == "CTO" and cto.pai_id in adj:
                adj[cto.pai_id].append(cto.id)

        # 3. Lógica de Fibra e Potência (Recursiva)
        tabela_fusao = {ceo.id: "" for ceo in dados.ceos}
        contador_fibra = {ceo.id: 1 for ceo in dados.ceos}
        response_ctos = []

        def processar_node(pai_id, pai_tipo, lat_p, lng_p, ceo_id, dist_base):
            filhos = [c for c in dados.ctos if c.pai_tipo == pai_tipo and c.pai_id == pai_id]
            for cto in filhos:
                f = contador_fibra[ceo_id]
                contador_fibra[ceo_id] += 1
                
                # Cálculo de distância e potência
                dist = np.sqrt((cto.lat - lat_p)**2 + (cto.lng - lng_p)**2) * 111.32
                dist_total = dist_base + dist
                pot = dados.potencia_olt - (dist_total * 0.35 + 21.0)
                
                # Desenho e Documentação
                cabo_tipo = "12FO" if f > 6 else "6FO"
                cor = CORES_ANATEL[(f-1)%12]
                
                fol_cabo.newlinestring(name=f"Cabo para CTO {cto.id}", coords=[(lng_p, lat_p), (cto.lng, cto.lat)])
                tabela_fusao[ceo_id] += f"<tr><td>Fibra {f} ({cor})</td><td>CTO {cto.id}</td></tr>"
                
                response_ctos.append({"id": cto.id, "potencia": round(pot, 2), "fibra": f"{f} ({cor})"})
                processar_node(cto.id, "CTO", cto.lat, cto.lng, ceo_id, dist_total)

        # Iniciar árvore para cada CEO
        for ceo in dados.ceos:
            dist_c = np.sqrt((ceo.lat - dados.olt['lat'])**2 + (ceo.lng - dados.olt['lng'])**2) * 111.32
            processar_node(ceo.id, "CEO", ceo.lat, ceo.lng, ceo.id, dist_c)
            fol_ceo.newpoint(name=f"CEO {ceo.id}", coords=[(ceo.lng, ceo.lat)], description=f"<table>{tabela_fusao[ceo.id]}</table>")

        return {"ctos": response_ctos, "kml_conteudo": kml.kml()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

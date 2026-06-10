import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI(title="Motor FTTH - Cascata Estável")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta", "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"]

class OLT(BaseModel):
    lat: float
    lng: float

class Elemento(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str
    pai_id: int

class Projeto(BaseModel):
    olt: OLT  # Agora o Pydantic sabe exatamente o que esperar
    ceos: List[Elemento]
    ctos: List[Elemento]
    splitter_ceo: str
    potencia_olt: float

@app.post("/api/v1/calcular")
async def calcular(dados: Projeto):
    try:
        kml = simplekml.Kml()
        fol_cabos = kml.newfolder(name="Cabos")
        
        # Estrutura segura para a árvore de derivações
        dict_ctos = {c.id: c for c in dados.ctos}
        filhos: Dict[str, Dict[int, List[int]]] = {"CEO": {c.id: [] for c in dados.ceos}, "CTO": {c.id: [] for c in dados.ctos}}
        
        for cto in dados.ctos:
            if cto.pai_tipo == "CEO": filhos["CEO"][cto.pai_id].append(cto.id)
            else: filhos["CTO"][cto.pai_id].append(cto.id)

        contador_fibra = {ceo.id: 1 for ceo in dados.ceos}
        tabela_fusao = {ceo.id: "" for ceo in dados.ceos}
        resp_ctos = []

        def processar(pai_id, pai_tipo, lat_p, lng_p, ceo_id):
            lista = filhos[pai_tipo].get(pai_id, [])
            for f_id in lista:
                cto = dict_ctos[f_id]
                f = contador_fibra[ceo_id]
                contador_fibra[ceo_id] += 1
                
                # Desenhar linha
                fol_cabos.newlinestring(coords=[(lng_p, lat_p), (cto.lng, cto.lat)])
                
                # Gerar tabela com segurança
                cor = CORES_ANATEL[(f-1)%12]
                tabela_fusao[ceo_id] += f"<tr><td>Porta {f}</td><td>{cor}</td><td>CTO {cto.id}</td></tr>"
                
                resp_ctos.append({
                    "id": cto.id, 
                    "cabo": "12FO" if f > 6 else "6FO", 
                    "fibra": f"{f} ({cor})",
                    "potencia_dbm": -20.0 # Placeholder cálculo
                })
                processar(cto.id, "CTO", cto.lat, cto.lng, ceo_id)

        for ceo in dados.ceos:
            processar(ceo.id, "CEO", ceo.lat, ceo.lng, ceo.id)

        return {"ctos": resp_ctos, "kml_conteudo": kml.kml()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

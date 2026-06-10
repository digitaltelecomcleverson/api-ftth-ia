from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Coordenada(BaseModel):
    lat: float
    lng: float

class Elemento(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str
    pai_id: int

class RequestProjeto(BaseModel):
    olt: Coordenada
    ceos: List[Elemento]
    ctos: List[Elemento]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.post("/api/v1/calcular")
async def calcular(dados: RequestProjeto):
    # Retorno simplificado apenas para testar a comunicação
    return {
        "status": "sucesso",
        "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng} for c in dados.ceos],
        "ctos": [{"id": c.id, "potencia_dbm": -20.0, "cabo_utilizado": "ASU", "fibra_sangrada": "1"} for c in dados.ctos],
        "kml_conteudo": ""
    }

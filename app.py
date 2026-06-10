from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import simplekml
import numpy as np

app = FastAPI(title="Motor FTTH Cascata")

# Habilita CORS para sua Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. DEFINIÇÃO DAS CLASSES NA ORDEM CORRETA
class Coordenada(BaseModel):
    lat: float
    lng: float

class ElementoCascata(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str
    pai_id: int

class RequestProjetoCascata(BaseModel):
    olt: Coordenada
    ceos: List[ElementoCascata]
    ctos: List[ElementoCascata]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

# 2. ROTA DE CÁLCULO
@app.post("/api/v1/calcular")
async def calcular(dados: RequestProjetoCascata):
    try:
        # A sua lógica de processamento original entra aqui
        # Exemplo simplificado para teste:
        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng} for c in dados.ceos],
            "ctos": [{"id": c.id, "potencia_dbm": -20.0} for c in dados.ctos],
            "kml_conteudo": "" # Aqui viria o seu kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

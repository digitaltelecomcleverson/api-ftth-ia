import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI(title="Motor FTTH - Engenharia de Sangria Estrita Anatel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = [
    "Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta",
    "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"
]

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

@app.get("/")
def read_root():
    return {"status": "Motor de Emendas Estrito Online"}

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma CEO no mapa.")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante caixas CTO no mapa antes de processar.")

    limite_caixas = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    
    # Validação de Limite PON
    for ceo in dados.ceos:
        qtd_ctos = len([c for c in dados.ctos if c.pon_id == ceo.pon_id])
        if qtd_ctos > limite_caixas:
            raise HTTPException(status_code=400, detail=f"A PON {ceo.pon_id} possui {qtd_ctos} CTOs vinculadas. O limite para o splitter {dados.splitter_ceo} é de {limite_caixas} caixas!")

    try:
        kml = simplekml.Kml(name="Projeto Executivo - Digital Telecom")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        dict_ceos = {c.id: c for c in dados.ceos}
        dict_ctos = {c.id: c for c in dados.ctos}
        
        # Estruturas de controle de árvore geográficas e lógicas
        adjacencia: Dict[str, List[int]] = {"CEO": [], "CTO": {c.id: [] for c in dados.ctos}}
        for cto in dados.ctos:
            if cto.pai_tipo == "CEO":
                adjacencia["CEO"].append(cto.id)
            else:
                if cto.pai_id in adjacencia["CTO"]:
                    adjacencia["CTO"][cto.pai_id].append(cto.id)

        dist_acumulada_nodos = {}
        fibra_atribuida_cto = {}
        tabela_emendas_master = {ceo.id: "" for ceo in dados.ceos}
        
        # Contador global sequencial de fibras que saem do splitter de 1º nível da CEO
        contador_fibra_ceo = {ceo.id: 1 for ceo in dados.ceos}

        # Função recursiva para descer a árvore calculando distâncias, bitolas e fixando as fibras de forma sequencial
        def processar_nodo_arvore(pai_tipo: str, pai_id: int, pai_lat: float, pai_lng: float, dist_base: float, ceo_vinculo_id: int):
            # Descobre os filhos diretos deste elemento
            filhos_ids = adjacencia["CEO"] if pai_tipo == "CEO" else adjacencia["CTO"].get(pai_id, [])
            
            # Ordena os filhos por proximidade geográfica para manter o cabo linear na rua
            filhos_ids.sort(key=lambda fid: (dict_ctos[fid].lat - pai_lat)**2 + (dict_ctos[fid].lng - pai_lng)**2)

            for f_id in filhos_ids:
                cto = dict_ctos[f_id]
                
                # Atribui a próxima fibra sequencial absoluta do splitter da CEO (Garante 1 a 12 sem pular ou repetir)
                f_num = contador_fibra_ceo[ceo_vinculo_id]
                contador_fibra_ceo[ceo_vinculo_id] += 1
                fibra_atribuida_cto[cto.id] = f_num

                # Orçamento de potência real no traçado do cabo
                dist_lance = np.sqrt((cto.lat - pai_lat)**2 + (cto.lng - pai_lng)**2) * 111.32
                dist_total_fibra = dist_base + dist_lance
                dist_acumulada_nodos[cto.id] = dist_total_fibra

                # Descobre o total de caixas penduradas adiante para dimensionar a bitola do cabo (6FO ou 12FO)
                def contar_jusante(node_id):
                    sub_filhos = adjacencia["CTO"].get(node_id, [])
                    tot = len(sub_filhos)
                    for sf in sub_filhos:
                        tot += contar_jusante(sf)
                    return tot
                
                carga_total_linha = contar_jusante(cto.id) + 1
                tipo_cabo = "12FO (ASU-120)" if f_num > 6 or (f_num + carga_total_linha - 1) > 6 else "6FO (ASU-80)"

                cor_idx = (f_num - 1) % 12
                cor_fibra_anatel = CORES_ANATEL[cor_idx]

                potencia = dados.potencia_olt - ((dist_total_fibra * 0.35) + perda_ceo = 10.5 + 10.5 + 0.6)

                # Gera o balão de informação unifilar da CTO no Google Earth
                html_cto = f"""
                <div style="font-family:sans-serif; width:290px; color:#333;">
                    <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 UNIFILAR - CTO {cto.id:02d}</h3>
                    <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                        <p><b>Porta Ativa:</b> PON {cto.pon_id:02d}</p>
                        <p><b>Origem do Lance:</b> {pai_tipo} {pai_id:02d}</p>
                        <p><b>Bitola do Cabo na Rua:</b> {tipo_cabo}</p>
                        <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                        <p style="color:#2563eb; font-weight:bold;">✂️ Sangria Ativa: Fibra {f_num:02d} ({cor_fibra_anatel})</p>
                        <p style="color:#555;">Fibras anteriores estão ocupadas. Fibras posteriores seguem passantes no tubo loose para as caixas derivadas.</p>
                        <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                        <p><b>Sinal Estimado:</b> <b>{potencia:.2f} dBm</b></p>
                    </div>
                </div>
                """
                pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
                pnt_cto.description = html_cto

                # Desenha a linha contínua unindo o pai ao filho (Sem zigue-zague, seguindo a rua reta)
                lin_c = fol_cabos_root.newlinestring(name=f"Cabo -> CTO {cto.id:02d}")
                lin_c.coords = [(pai_lng, pai_lat), (cto.lng, cto.lat)]
                lin_c.style.linestyle.width = 3
                lin_c.style.linestyle.color = "ff00ff00" # Verde Distribuição

                # Alimenta a tabela unifilar da CEO com o relatório real de fusão do splitter
                tabela_emendas_master[ceo_vinculo_id] += f"""
                <tr>
                    <td style='padding:5px; border:1px solid #ddd;'><b>Saída 0{f_num} (Splitter)</b></td>
                    <td style='padding:5px; border:1px solid #ddd; color:#2563eb; font-weight:bold;'>Fibra {f_num:02d} ({cor_fibra_anatel})</td>
                    <td style='padding:5px; border:1px solid #ddd;'>➡️ Conecta na CTO {cto.id:02d} (Via {pai_tipo} {pai_id:02d})</td>
                </tr>
                """

                # Executa a recursão descendo para as caixas que derivam desta CTO atual
                processar_nodo_arvore("CTO", cto.id, cto.lat, cto.lng, dist_total_fibra, ceo_vinculo_id)

        # Inicia o processamento da árvore para cada CEO implantada no mapa
        for ceo in dados.ceos:
            dist_base_ceo = np.sqrt((ceo.lat - dados.olt.lat)**2 + (ceo.lng - dados.olt.lng)**2) * 111.32
            
            # Processa os filhos desta CEO específica
            processar_nodo_arvore("CEO", ceo.id, ceo.lat, ceo.lng, dist_base_ceo, ceo.id)

            # Injeta a tabela HTML completa dentro da descrição da CEO no KML
            html_master_ceo = f"""
            <div style="font-family:sans-serif; width:390px; color:#333;">
                <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0; font-size:14px;">📋 RELATÓRIO DE EMENDA - CEO {ceo.id:02d}</h3>
                <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                    <p><b>Porta OLT Alimentadora:</b> PON {ceo.pon_id:02d}</p>
                    <p><b>Splitter de 1º Nível Interno:</b> {dados.splitter_ceo}</p>
                    <p style="color:#16a34a; font-weight:bold;">🟢 Entrada Primária: Fibra 01 (Verde) do Cabo Tronco ➡️ IN do Splitter</p>
                    <hr style="margin:8px 0; border:0; border-top:1px solid #eee;">
                    <h4 style="margin:0 0 5px 0; color:#1e40af;">Mapa de Fusões do Splitter para o Cabo de Distribuição:</h4>
                    <table style="width:100%; border-collapse:collapse; font-size:11px; text-align:left;" border="1" cellpadding="4" cellspacing="0">
                        <tr style="background:#f3f4f6; font-weight:bold;">
                            <th>Saída Splitter</th>
                            <th>Fusão Óptica (Distribuição)</th>
                            <th>Destino / Caixas Atendidas</th>
                        </tr>
                        {tabela_emendas_master[ceo.id]}
                    </table>
                </div>
            </div>
            """
            pnt_ceo = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt_ceo.description = html_master_ceo

            # Desenha o Cabo Tronco Vermelho vindo da OLT
            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff"

        # Monta a resposta de CTOs organizada para retornar para o Leaflet desenhar na tela
        ctos_retorno = []
        for cto in dados.ctos:
            f_num = fibra_atribuida_cto.get(cto.id, 1)
            cor_idx = (f_num - 1) % 12
            ctos_retorno.append({
                "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id, "ceo_vinculo": cto.ceo_vinculo,
                "potencia_dbm": round(dist_acumulada_nodos.get(cto.id, 0) * -0.35 - 21.0, 2),
                "cabo_utilizado": "12FO (ASU-120)" if f_num > 6 else "6FO (ASU-80)",
                "fibra_sangrada": f"Fibra {f_num:02d} ({CORES_ANATEL[cor_idx]})"
            })

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": ctos_retorno,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no motor unifilar estrito: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

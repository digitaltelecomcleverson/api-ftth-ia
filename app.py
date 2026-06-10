import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Motor FTTH - Rastreamento Estrito de Fibras Anatel")

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
    return {"status": "Motor de Rastreamento de Fibras Online"}

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma CEO no mapa.")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante CTOs no mapa antes de processar.")

    limite_caixas = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    for ceo in dados.ceos:
        qtd_ctos = len([c for c in dados.ctos if c.pon_id == ceo.pon_id])
        if qtd_ctos > limite_caixas:
            raise HTTPException(status_code=400, detail=f"A PON {ceo.pon_id} possui {qtd_ctos} CTOs. O limite para o splitter {dados.splitter_ceo} é de {limite_caixas} caixas!")

    try:
        kml = simplekml.Kml(name="Projeto Executivo - Digital Telecom")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        dict_ceos = {c.id: c for c in dados.ceos}
        dict_ctos_enviadas = {c.id: c for c in dados.ctos}
        
        # Estruturas para controle de herança na árvore de derivações
        dist_acumulada_nodos = {}
        fibra_atribuida_cto = {}   # Guarda o número da fibra real (1 a 12) associada a cada CTO ID
        registro_sub_arvores = {}  # Guarda a sequência física de caminhos para saber a bitola do cabo

        # Passo 1: Determinar a ordem cronológica de atendimento descendo a árvore (Mapeamento de Pais)
        elementos_para_processar = dados.ctos.copy()
        lista_ordenada_calculo = []
        
        # Dicionários de filhos para o cálculo de carga a jusante
        def obter_max_indice_linha(id_nodo):
            filhos = [c for c in dados.ctos if c.pai_tipo == "CTO" and c.pai_id == id_nodo]
            if not filhos:
                return 1
            # Retorna o tamanho total do barramento subsequente
            total = len(filhos)
            for f in filhos:
                total += obter_max_indice_linha(f.id)
            return total

        # Ordenação estável da árvore baseada no nível de dependência (CEO primeiro, depois filhos)
        cont_seguranca = 0
        while len(elementos_para_processar) > 0 and cont_seguranca < 200:
            cont_seguranca += 1
            for cto in list(elementos_para_processar):
                if cto.pai_tipo == "CEO":
                    lista_ordenada_calculo.append(cto)
                    elementos_para_processar.remove(cto)
                else:
                    # Só processa o filho se o pai já estiver na lista calculada
                    if any(x.id == cto.pai_id for x in lista_ordenada_calculo):
                        lista_ordenada_calculo.append(cto)
                        elementos_para_processar.remove(cto)

        # Contadores de uso de fibra na saída da CEO por Ramal PON
        # Garante que a distribuição comece em 1 (Verde) e suba sequencialmente de forma contínua
        proxima_fibra_disponivel_pon = {ceo.id: 1 for ceo in dados.ceos}
        tabela_emendas_ceo = {ceo.id: "" for ceo in dados.ceos}

        response_ctos = []

        # Passo 2: Processar as CTOs na ordem correta de lançamento de cabo
        for cto in lista_ordenada_calculo:
            pai_lat, pai_lng, dist_base, ceo_ancora_id = 0.0, 0.0, 0.0, 1
            
            if cto.pai_tipo == "CEO":
                ceo_pai = dict_ceos[cto.pai_id]
                pai_lat, pai_lng = ceo_pai.lat, ceo_pai.lng
                ceo_ancora_id = ceo_pai.id
                dist_base = np.sqrt((ceo_pai.lat - dados.olt.lat)**2 + (ceo_pai.lng - dados.olt.lng)**2) * 111.32
                
                # Consome a próxima fibra disponível sequencial daquela caixa de emenda
                fibra_num_real = proxima_fibra_disponivel_pon[ceo_ancora_id]
                proxima_fibra_disponivel_pon[ceo_ancora_id] += 1
            else:
                cto_pai = dict_ctos_enviadas[cto.pai_id]
                pai_lat, pai_lng = cto_pai.lat, cto_pai.lng
                dist_base = dist_acumulada_nodos[cto.pai_id]
                
                # Encontra a CEO ancestral subindo os nós
                nodo_atual = cto
                while nodo_atual.pai_tipo == "CTO":
                    nodo_atual = dict_ctos_enviadas[nodo_atual.pai_id]
                ceo_ancora_id = nodo_atual.pai_id
                
                # Regra de Engenharia: Em barramento ou derivação, herda a contagem sequencial continuada da CEO
                fibra_num_real = proxima_fibra_disponivel_pon[ceo_ancora_id]
                proxima_fibra_disponivel_pon[ceo_ancora_id] += 1

            fibra_atribuida_cto[cto.id] = fibra_num_real

            # Orçamento de potência real no traçado físico
            dist_lance = np.sqrt((cto.lat - pai_lat)**2 + (cto.lng - pai_lng)**2) * 111.32
            dist_total_fibra = dist_base + dist_lance
            dist_acumulada_nodos[cto.id] = dist_total_fibra

            # Dimensionamento do Cabo (6FO ou 12FO) com base na carga total da linha de poste
            carga_ramificacao = obter_max_indice_linha(cto.id)
            tipo_cabo = "12FO (ASU-120)" if (carga_ramificacao + fibra_num_real) > 6 else "6FO (ASU-80)"

            # Tratamento estrito do limite físico do cabo para evitar estouro de cores
            cor_idx = (fibra_num_real - 1) % 12
            cor_fibra_anatel = CORES_ANATEL[cor_idx]

            potencia = dados.potencia_olt - ((dist_total_fibra * 0.35) + 10.5 + 10.5 + 0.6)

            # Documentação interna de sangria da CTO
            html_cto = f"""
            <div style="font-family:sans-serif; width:300px; color:#333;">
                <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 UNIFILAR - CTO {cto.id:02d}</h3>
                <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                    <p><b>Porta Ativa:</b> PON {cto.pon_id:02d}</p>
                    <p><b>Modelo do Cabo da Rua:</b> {tipo_cabo}</p>
                    <p><b>Origem Física do Lance:</b> {cto.pai_tipo} {cto.pai_id:02d}</p>
                    <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                    <p style="color:#2563eb; font-weight:bold;">✂️ Sangria em Campo: Fibra {fibra_num_real:02d} ({cor_fibra_anatel})</p>
                    <p style="color:#555;">As fibras anteriores estão cortadas/ocupadas nas caixas traseiras. As fibras subsequentes seguem passantes.</p>
                    <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                    <p><b>Sinal Estimado:</b> <b>{potencia:.2f} dBm</b></p>
                </div>
            </div>
            """
            pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
            pnt_cto.description = html_cto

            # Desenha linha reta ligando o pai ao filho sem cruzar quarteirões
            lin_c = fol_cabos_root.newlinestring(name=f"Cabo Trecho -> CTO {cto.id:02d}")
            lin_c.coords = [(pai_lng, pai_lat), (cto.lng, cto.lat)]
            lin_c.style.linestyle.width = 3
            lin_c.style.linestyle.color = "ff00ff00" # Verde Distribuição

            # Registra a linha de fusão na tabela master da CEO correspondente
            tabela_emendas_ceo[ceo_ancora_id] += f"""
                <tr>
                    <td style='padding:5px; border:1px solid #ddd;'><b>Porta 0{fibra_num_real} (Splitter)</b></td>
                    <td style='padding:5px; border:1px solid #ddd; color:blue;'>➡️ Fusão na Fibra {fibra_num_real:02d} ({cor_fibra_anatel})</td>
                    <td style='padding:5px; border:1px solid #ddd;'>Destinada à CTO {cto.id:02d} (Via {cto.pai_tipo} {cto.pai_id:02d})</td>
                </tr>
            """

            response_ctos.append({
                "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id, "ceo_vinculo": ceo_ancora_id,
                "potencia_dbm": round(potencia, 2), "cabo_utilizado": tipo_cabo, "fibra_sangrada": f"Fibra {fibra_num_real} ({cor_fibra_anatel})"
            })

        # Passo 3: Fechar os balões de informação das CEOs injetando a tabela unifilar de emendas do splitter
        for ceo in dados.ceos:
            html_master_ceo = f"""
            <div style="font-family:sans-serif; width:380px; color:#333;">
                <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0; font-size:14px;">📋 DOCUMENTAÇÃO DE EMENDA - CEO {ceo.id:02d}</h3>
                <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                    <p><b>Atendimento Primário:</b> Porta PON {ceo.pon_id:02d}</p>
                    <p><b>Splitter de 1º Nível alocado:</b> {dados.splitter_ceo}</p>
                    <p style="color:#16a34a; font-weight:bold;">🟢 Alimentação: Fibra 01 (Verde) do Cabo Tronco ➡️ IN do Splitter</p>
                    <hr style="margin:8px 0; border:0; border-top:1px solid #eee;">
                    <h4 style="margin:0 0 5px 0; color:#1e40af;">Mapa de Fusões do Splitter para os Cabos de Distribuição:</h4>
                    <table style="width:100%; border-collapse:collapse; font-size:11px; text-align:left;">
                        <tr style="background:#f3f4f6; font-weight:bold;">
                            <th style='padding:5px; border:1px solid #ddd;'>Saída Splitter</th>
                            <th style='padding:5px; border:1px solid #ddd;'>Fusão Óptica</th>
                            <th style='padding:5px; border:1px solid #ddd;'>Destino Final</th>
                        </tr>
                        {tabela_emendas_ceo[ceo.id]}
                    </table>
                </div>
            </div>
            """
            pnt_ceo = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt_ceo.description = html_master_ceo

            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff"

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor de emenda estrito: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

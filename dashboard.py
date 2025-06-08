import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import plotly.express as px # <--- NOVO IMPORT para gráficos interativos

# --- Configurações da Página (igual) ---
st.set_page_config(
    page_title="Dashboard de Leads",
    page_icon="🤖",
    layout="wide"
)

# --- Função de Carregamento de Dados (igual) ---
@st.cache_data(ttl=600)
def load_data():
    """Função para carregar dados da Planilha Google e retornar um DataFrame do Pandas."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
                 "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
        
        creds_json_str = os.getenv("GDRIVE_CREDENTIALS")
        if creds_json_str:
            creds_dict = json.loads(creds_json_str)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)

        client = gspread.authorize(creds)
        sheet = client.open("Leads do Bot Telegram").sheet1
        data = sheet.get_all_records()
        
        dataframe = pd.DataFrame(data)
        return dataframe

    except Exception as e:
        st.error(f"Erro ao carregar os dados da planilha: {e}")
        return pd.DataFrame()

# --- Início da Interface ---
st.title("🤖 Dashboard de Análise de Leads")

df = load_data()

if not df.empty:
    # --- BARRA LATERAL COM FILTROS (NOVO!) ---
    st.sidebar.header("Filtros Interativos")

    # Filtro por Classificação
    classificacoes = df['Classificação'].unique()
    filtro_classificacao = st.sidebar.multiselect(
        "Filtrar por Classificação:",
        options=classificacoes,
        default=classificacoes  # Por padrão, todas as opções são selecionadas
    )

    # Filtro por Interesse
    interesses = df['Interesse'].unique()
    filtro_interesse = st.sidebar.multiselect(
        "Filtrar por Interesse:",
        options=interesses,
        default=interesses
    )

    # --- LÓGICA DE FILTRAGEM (NOVO!) ---
    # Cria um novo DataFrame que será filtrado de acordo com a seleção do usuário
    df_filtrado = df[
        df['Classificação'].isin(filtro_classificacao) &
        df['Interesse'].isin(filtro_interesse)
    ]

    # --- Métricas Principais (AGORA USAM O DATAFRAME FILTRADO) ---
    st.subheader("Métricas Gerais (com base nos filtros)")
    
    col1, col2, col3 = st.columns(3)
    
    total_leads_filtrado = len(df_filtrado)
    col1.metric("Leads (Filtro Atual)", total_leads_filtrado)
    
    leads_quentes_filtrado = df_filtrado[df_filtrado['Classificação'] == 'Lead Quente'].shape[0]
    col2.metric("Leads Quentes 🔥 (Filtro Atual)", leads_quentes_filtrado)

    # --- Gráficos (AGORA USAM O DATAFRAME FILTRADO) ---
    st.subheader("Visualizações Dinâmicas")
    
    col_graf1, col_graf2 = st.columns(2) # Duas colunas para os gráficos

    # Gráfico de Barras por Classificação
    contagem_classificacao_filtrada = df_filtrado['Classificação'].value_counts()
    col_graf1.bar_chart(contagem_classificacao_filtrada)

    # Gráfico de Pizza por Interesse (NOVO!)
    contagem_interesse_filtrada = df_filtrado['Interesse'].value_counts()
    if not contagem_interesse_filtrada.empty:
        fig_pie = px.pie(
            contagem_interesse_filtrada,
            values=contagem_interesse_filtrada.values,
            names=contagem_interesse_filtrada.index,
            title="Proporção de Leads por Interesse"
        )
        col_graf2.plotly_chart(fig_pie, use_container_width=True)
    else:
        col_graf2.warning("Nenhum dado para exibir no gráfico de pizza com os filtros atuais.")


    # --- Tabela de Dados (AGORA USA O DATAFRAME FILTRADO) ---
    st.subheader("Detalhes dos Leads (Filtro Aplicado)")
    st.dataframe(df_filtrado)

else:
    st.warning("Nenhum dado encontrado na planilha ou falha no carregamento.")
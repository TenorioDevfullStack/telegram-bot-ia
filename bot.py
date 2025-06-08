import os
import json
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- CONFIGURAÇÕES E INICIALIZAÇÃO (continua igual) ---
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    genai.configure(api_key=GOOGLE_API_KEY)
    logger.info("API do Google AI (Gemini) configurada.")
except Exception as e:
    logger.error(f"Erro fatal ao configurar a API do Google: {e}")
    exit()

# --- NOVA ESTRUTURA PARA GERIR CONVERSAS ---

# Um dicionário para guardar as conversas ativas de cada usuário
# Chave: user_id, Valor: objeto de chat do Gemini
active_chats = {}

# O cérebro do nosso bot: a instrução mestra que define seu comportamento
# Esta é a parte mais importante da nova lógica!
SYSTEM_PROMPT = """
Você é um assistente de vendas virtual, seu nome é LeadBot. Você é amigável, profissional e muito eficiente.
Sua missão é conversar com um potencial cliente para entender suas necessidades e coletar as seguintes informações:
1. Nome Completo
2. Endereço de E-mail
3. Número de Telefone (WhatsApp)
4. Área de Interesse Principal (o serviço que mais lhe chama a atenção)

REGRAS IMPORTANTES:
- Faça APENAS UMA pergunta de cada vez.
- Seja natural e conversacional, não pareça um robô preenchendo um formulário.
- Inicie a conversa se apresentando e pedindo o nome do usuário.
- Após coletar uma informação, confirme-a de forma sutil e peça a próxima.
- Quando você tiver coletado com sucesso TODAS as 4 informações (Nome, Email, Telefone e Interesse), finalize a sua resposta com a frase exata e sem formatação adicional: [CONVERSA_FINALIZADA]
- Não use esta frase em nenhuma outra circunstância.
"""

# As funções de salvar na planilha e classificar o lead continuam as mesmas
# ... (Copie aqui as suas funções `classify_lead_with_gemini` e `save_lead_to_sheet` da versão anterior) ...
async def classify_lead_with_gemini(lead_data: dict) -> str:
    logger.info("Enviando dados para o Gemini para classificação...")
    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        prompt = f"""
        Você é um analista de vendas sênior. Analise os dados do lead abaixo e classifique seu potencial.
        Dados: {json.dumps(lead_data)}
        Use estritamente uma das seguintes classificações: "Lead Quente", "Lead Morno", "Lead Frio".
        Responda APENAS com a classificação.
        """
        response = await model.generate_content_async(prompt)
        classification = response.text.strip()
        logger.info(f"Classificação recebida do Gemini: '{classification}'")
        return classification
    except Exception as e:
        logger.error(f"Ocorreu um erro ao chamar a API do Gemini para classificação: {e}")
        return "Erro na Classificação"

async def save_lead_to_sheet(lead_data: dict):
    """Salva os dados de um lead em uma Planilha Google, lendo as credenciais de forma segura."""
    logger.info("Salvando lead na Planilha Google...")
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
                 "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]

        creds_json_str = os.getenv("GDRIVE_CREDENTIALS")

        if creds_json_str:
            # Se estiver na nuvem (Render), lê as credenciais da variável de ambiente
            logger.info("Usando credenciais da variável de ambiente.")
            creds_dict = json.loads(creds_json_str)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            # Se estiver rodando localmente, usa o ficheiro credentials.json
            logger.info("Usando ficheiro local credentials.json.")
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)

        client = gspread.authorize(creds)
        sheet = client.open("Leads do Bot Telegram").sheet1
        data_row = [
            lead_data.get('Nome', ''),
            lead_data.get('Email', ''),
            lead_data.get('Telefone', ''),
            lead_data.get('Interesse', ''),
            lead_data.get('Classificação', ''),
            logging.Formatter().formatTime(logging.makeLogRecord({}))[:19]
        ]
        sheet.append_row(data_row)
        logger.info("Lead salvo com sucesso!")

    except Exception as e:
        logger.error(f"Erro ao salvar na Planilha Google: {e}")

# --- NOVAS FUNÇÕES PRINCIPAIS DO BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia uma nova conversa ou reinicia uma existente."""
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    
    # Se o usuário já tiver uma conversa ativa, ela é reiniciada.
    active_chats[user_id] = None 
    
    await update.message.reply_text(f"Olá, {user_name}! 👋 Eu sou o LeadBot, seu assistente de vendas virtual. Vamos começar?")
    await update.message.reply_text("Para iniciarmos, por favor, me diga seu nome completo.")


async def handle_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gere toda a conversa usando a IA do Gemini."""
    user_id = update.message.from_user.id
    user_message = update.message.text

    # Verifica se existe uma conversa ativa para este usuário
    if user_id not in active_chats or active_chats[user_id] is None:
        # Se não houver, cria uma nova sessão de chat com o Gemini
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        # Inicia o chat e guarda na memória (active_chats)
        active_chats[user_id] = model.start_chat(history=[
            {'role': 'user', 'parts': [SYSTEM_PROMPT]},
            {'role': 'model', 'parts': ["Olá! Eu sou o LeadBot, seu assistente de vendas virtual. Para começarmos, qual é o seu nome completo?"]}
        ])

    try:
        # Envia a mensagem do usuário para a sessão de chat do Gemini
        chat_session = active_chats[user_id]
        response = await chat_session.send_message_async(user_message)
        ai_response_text = response.text

        # Verifica se a IA sinalizou o fim da coleta de dados
        if "[CONVERSA_FINALIZADA]" in ai_response_text:
            # Remove a frase de sinalização da mensagem final
            final_message_to_user = ai_response_text.replace("[CONVERSA_FINALIZADA]", "").strip()
            await update.message.reply_text(final_message_to_user)
            await update.message.reply_text("Obrigado! Só um momento enquanto processo e guardo suas informações.")
            
            logger.info(f"Conversa finalizada para o usuário {user_id}. Extraindo dados...")

            # CRIA UMA NOVA CHAMADA À IA PARA EXTRAIR OS DADOS DE FORMA ESTRUTURADA
            model_extractor = genai.GenerativeModel('gemini-1.5-pro-latest')
            extraction_prompt = f"""
            Analise o seguinte histórico de conversa e extraia as informações de Nome, Email, Telefone e Interesse do usuário.
            Responda APENAS com um objeto JSON válido. Se uma informação não for encontrada, use o valor "Não informado".
            Exemplo de resposta: {{"Nome": "João Silva", "Email": "joao.silva@email.com", "Telefone": "11999998888", "Interesse": "Integração com IA"}}

            Histórico da Conversa:
            {chat_session.history}
            """
            
            extraction_response = await model_extractor.generate_content_async(extraction_prompt)
            # Limpa a resposta para garantir que é um JSON válido
            lead_json_str = extraction_response.text.strip().replace("```json", "").replace("```", "")
            
            try:
                lead_data = json.loads(lead_json_str)
                logger.info(f"Dados extraídos: {lead_data}")

                # Usa as funções que já tínhamos para classificar e salvar
                classification = await classify_lead_with_gemini(lead_data)
                lead_data['Classificação'] = classification
                await save_lead_to_sheet(lead_data)
                await update.message.reply_text("Pronto! Suas informações foram registradas com sucesso. Entraremos em contato em breve.")

            except json.JSONDecodeError:
                logger.error("Erro ao decodificar o JSON extraído da IA.")
                await update.message.reply_text("Tive um problema ao organizar suas informações. Poderia tentar novamente mais tarde?")

            # Limpa a conversa da memória
            del active_chats[user_id]

        else:
            # Se a conversa não terminou, apenas envia a resposta da IA para o usuário
            await update.message.reply_text(ai_response_text)

    except Exception as e:
        logger.error(f"Erro durante a conversa: {e}")
        await update.message.reply_text("Desculpe, ocorreu um erro. Vamos tentar reiniciar. Por favor, envie /start novamente.")
        if user_id in active_chats:
            del active_chats[user_id]


def main() -> None:
    """Função principal que inicia o bot com a nova lógica."""
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.error("Erro: Token do Telegram não encontrado!")
        return
        
    application = Application.builder().token(token).build()

    # Adiciona os novos handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation))

    logger.info("Bot dinâmico iniciado! Pressione Ctrl+C para parar.")
    application.run_polling()


if __name__ == "__main__":
    main()
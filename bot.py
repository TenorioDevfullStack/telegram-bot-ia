# (Imports e configurações iniciais continuam iguais)
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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

active_chats = {}

# --- PROMPT MESTRE ATUALIZADO (MELHORIA 1) ---
SYSTEM_PROMPT = """
Você é um assistente de vendas virtual, seu nome é LeadBot. Você é amigável, profissional e muito eficiente.
Sua missão é conversar com um potencial cliente para entender suas necessidades e coletar as seguintes informações:
1. Nome Completo
2. Endereço de E-mail
3. Número de Telefone (WhatsApp)
4. Área de Interesse Principal (o serviço que mais lhe chama a atenção)

REGRAS IMPORTANTES:
- Faça APENAS UMA pergunta de cada vez.
- Seja natural e direto. Após receber uma informação, peça a próxima sem fazer uma frase de confirmação.
- Inicie a conversa se apresentando e pedindo o nome do usuário.
- Quando você tiver coletado com sucesso TODAS as 4 informações (Nome, Email, Telefone e Interesse), finalize a sua resposta com a frase exata e sem formatação adicional: [CONVERSA_FINALIZADA]
- Não use esta frase em nenhuma outra circunstância.
"""

# ... (As funções `notify_admin_on_hot_lead`, `save_lead_to_sheet` e `classify_lead_with_gemini` continuam iguais) ...
async def notify_admin_on_hot_lead(context: ContextTypes.DEFAULT_TYPE, lead_data: dict):
    admin_id = os.getenv("ADMIN_CHAT_ID")
    if not admin_id:
        logger.warning("ADMIN_CHAT_ID não está configurado. Não é possível enviar notificação.")
        return
    try:
        message = f"""
        <b>🔥 Lead Quente Capturado! 🔥</b>
        <b>Nome:</b> {lead_data.get('Nome', 'Não informado')}
        <b>Email:</b> {lead_data.get('Email', 'Não informado')}
        <b>Telefone:</b> {lead_data.get('Telefone', 'Não informado')}
        <b>Interesse:</b> {lead_data.get('Interesse', 'Não informado')}
        """
        await context.bot.send_message(
            chat_id=admin_id, text=message, parse_mode=ParseMode.HTML
        )
        logger.info(f"Notificação de Lead Quente enviada para o admin (ID: {admin_id})")
    except Exception as e:
        logger.error(f"Falha ao enviar notificação para o admin: {e}")

async def save_lead_to_sheet(lead_data: dict):
    logger.info("Salvando lead na Planilha Google...")
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
        data_row = [
            lead_data.get('Nome', ''), lead_data.get('Email', ''), lead_data.get('Telefone', ''),
            lead_data.get('Interesse', ''), lead_data.get('Classificação', ''),
            logging.Formatter().formatTime(logging.makeLogRecord({}))[:19]
        ]
        sheet.append_row(data_row)
        logger.info("Lead salvo com sucesso!")
    except Exception as e:
        logger.error(f"Erro ao salvar na Planilha Google: {e}")

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    active_chats[user_id] = None 
    await update.message.reply_text(f"Olá, {user_name}! 👋 Eu sou o LeadBot, seu assistente de vendas virtual.")
    
    # Inicia a conversa diretamente, chamando a função principal
    await handle_conversation(update, context)

# --- LÓGICA DE CONVERSA PRINCIPAL (ATUALIZADA - MELHORIA 2) ---

async def handle_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_message = update.message.text

    # --- NOVA LÓGICA DE VERIFICAÇÃO ---
    # 1. Verifica se a conversa já foi concluída
    if active_chats.get(user_id) == "COMPLETED":
        await update.message.reply_text("Fico feliz em ter ajudado! Se precisar iniciar uma nova cotação, pode usar o comando /start a qualquer momento.")
        return

    # 2. Se não foi concluída, verifica se é uma conversa nova ou em andamento
    if user_id not in active_chats or active_chats.get(user_id) is None:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        # A primeira mensagem do usuário (após o /start) será tratada aqui
        # O start agora é mais simples e apenas chama esta função
        initial_user_message = "Olá, meu nome é " + update.message.from_user.first_name
        active_chats[user_id] = model.start_chat(history=[
            {'role': 'user', 'parts': [SYSTEM_PROMPT]},
            {'role': 'model', 'parts': ["Olá! Eu sou o LeadBot, seu assistente de vendas virtual. Para começarmos, qual é o seu nome completo?"]}
        ])
        # Define a mensagem do usuário para ser a primeira da conversa real
        user_message = initial_user_message

    try:
        chat_session = active_chats[user_id]
        response = await chat_session.send_message_async(user_message)
        ai_response_text = response.text

        if "[CONVERSA_FINALIZADA]" in ai_response_text:
            final_message_to_user = ai_response_text.replace("[CONVERSA_FINALIZADA]", "").strip()
            if final_message_to_user: # Envia a última mensagem da IA se não estiver vazia
                 await update.message.reply_text(final_message_to_user)
            await update.message.reply_text("Obrigado! A processar e guardar as suas informações...")
            
            # (A lógica de extração, classificação e salvamento continua igual)
            # ...
            model_extractor = genai.GenerativeModel('gemini-1.5-pro-latest')
            extraction_prompt = f"""
            Analise o seguinte histórico de conversa e extraia as informações de Nome, Email, Telefone e Interesse do usuário.
            Responda APENAS com um objeto JSON válido. Se uma informação não for encontrada, use o valor "Não informado".
            Histórico da Conversa:
            {chat_session.history}
            """
            extraction_response = await model_extractor.generate_content_async(extraction_prompt)
            lead_json_str = extraction_response.text.strip().replace("```json", "").replace("```", "")
            
            try:
                lead_data = json.loads(lead_json_str)
                logger.info(f"Dados extraídos: {lead_data}")
                classification = await classify_lead_with_gemini(lead_data)
                lead_data['Classificação'] = classification
                
                if classification == "Lead Quente":
                    await notify_admin_on_hot_lead(context, lead_data)

                await save_lead_to_sheet(lead_data)
                await update.message.reply_text("Pronto! As suas informações foram registadas com sucesso. Entraremos em contato em breve.")

            except json.JSONDecodeError:
                logger.error("Erro ao decodificar o JSON extraído da IA.")
                await update.message.reply_text("Tive um problema ao organizar as suas informações. Pode tentar novamente mais tarde?")

            # --- MUDANÇA IMPORTANTE AQUI ---
            # Em vez de apagar, marcamos como concluído
            active_chats[user_id] = "COMPLETED"

        else:
            await update.message.reply_text(ai_response_text)
    except Exception as e:
        logger.error(f"Erro durante a conversa: {e}")
        await update.message.reply_text("Desculpe, ocorreu um erro. Vamos tentar reiniciar. Por favor, envie /start novamente.")
        if user_id in active_chats:
            del active_chats[user_id]


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    application = Application.builder().token(token).build()
    # A função start agora é o ponto de entrada que chama a handle_conversation
    application.add_handler(CommandHandler("start", start))
    # A handle_conversation lida com as mensagens de texto que não são comandos
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation))
    logger.info("Bot dinâmico (v2 - refinado) iniciado! Pressione Ctrl+C para parar.")
    application.run_polling()

if __name__ == "__main__":
    main()
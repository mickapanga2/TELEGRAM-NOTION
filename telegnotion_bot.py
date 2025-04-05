import logging
import os
import datetime
from dotenv import load_dotenv
from telegram import Update, File as TelegramFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from notion_client import Client, APIResponseError

# --- Configuration ---
load_dotenv()  # Charge les variables depuis .env

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")

# Vérification initiale des variables d'environnement
if not all([TELEGRAM_TOKEN, NOTION_TOKEN, NOTION_DB_ID]):
    raise ValueError("Erreur: Assurez-vous que TELEGRAM_BOT_TOKEN, NOTION_API_KEY, et NOTION_DATABASE_ID sont définis dans le fichier .env")

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING) # Réduit le bruit des logs de la lib HTTP
logger = logging.getLogger(__name__)

# Initialisation du client Notion
try:
    notion = Client(auth=NOTION_TOKEN)
    # Test rapide de connexion en listant les bases (optionnel mais utile)
    # notion.search(filter={"property": "object", "value": "database"})
    logger.info("Client Notion initialisé avec succès.")
except Exception as e:
    logger.error(f"Erreur lors de l'initialisation du client Notion: {e}")
    exit() # Arrête le script si Notion ne peut pas être initialisé

# --- Fonctions Utilitaires ---

async def save_to_notion(page_properties: dict) -> bool:
    """Crée une nouvelle page dans la base de données Notion spécifiée."""
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties=page_properties
        )
        logger.info("Page créée avec succès dans Notion.")
        return True
    except APIResponseError as e:
        logger.error(f"Erreur API Notion: {e.code} - {e.body}")
        return False
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la sauvegarde dans Notion: {e}")
        return False

def get_text_properties(text: str) -> dict:
    """Prépare les propriétés Notion pour un message texte."""
    title = text[:30] # Utilise les 100 premiers caractères comme titre
    return {
        # IMPORTANT: Assurez-vous que les noms des propriétés ("Name", "Type", "Contenu")
        # correspondent EXACTEMENT à ceux de votre base de données Notion (sensible à la casse).
        "Name": {
            "title": [{"text": {"content": title}}]
        },
        "Type": {
            "select": {"name": "Texte"} # Assurez-vous que l'option "Texte" existe dans votre Select
        },
        "Contenu": {
             # Utilisez 'rich_text' si la colonne 'Contenu' est de type Rich Text
             "rich_text": [{"type": "text", "text": {"content": text}}]
             # Utilisez 'text' si elle est de type Text (plus ancien, moins courant)
             # "text": [{"content": text}] # Décommentez si type Text
        }
        # "Reçu le" est automatiquement ajouté si la colonne est de type "Created time"
    }

async def get_file_properties(file: TelegramFile, file_type: str, filename: str = None) -> dict:
    """Prépare les propriétés Notion pour une image ou un document."""
    file_url = file.file_path # URL de téléchargement temporaire fournie par Telegram
    page_title = f"{file_type.capitalize()}: {filename or datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    return {
        "Name": {
            "title": [{"text": {"content": page_title[:100]}}] # Limite la longueur du titre
        },
        "Type": {
            "select": {"name": file_type.capitalize()} # Assurez-vous que les options "Image", "Document" existent
        },
        "Fichier URL": {
            "url": file_url
        }
    }

# --- Gestionnaires de Commandes et Messages Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la commande /start."""
    await update.message.reply_text(
        "Bonjour ! Envoyez-moi du texte, une image ou un document, et je le sauvegarderai dans votre base de données Notion."
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les messages texte."""
    message_text = update.message.text
    user = update.effective_user
    logger.info(f"Message texte reçu de {user.first_name} ({user.id}): {message_text[:50]}...")

    await update.message.reply_text("Traitement du texte...")

    properties = get_text_properties(message_text)
    success = await save_to_notion(properties)

    if success:
        await update.message.reply_text("Texte sauvegardé dans Notion !")
    else:
        await update.message.reply_text("Oups ! Une erreur s'est produite lors de la sauvegarde dans Notion.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les messages contenant des photos."""
    user = update.effective_user
    logger.info(f"Photo reçue de {user.first_name} ({user.id})")

    await update.message.reply_text("Traitement de l'image...")

    # Prend la plus grande résolution disponible
    photo_file = await context.bot.get_file(update.message.photo[-1].file_id)

    properties = await get_file_properties(photo_file, "Image")
    success = await save_to_notion(properties)

    if success:
        await update.message.reply_text("Image sauvegardée dans Notion !")
    else:
        await update.message.reply_text("Oups ! Une erreur s'est produite lors de la sauvegarde dans Notion.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les messages contenant des documents."""
    user = update.effective_user
    doc = update.message.document
    logger.info(f"Document reçu de {user.first_name} ({user.id}): {doc.file_name}")

    await update.message.reply_text("Traitement du document...")

    doc_file = await context.bot.get_file(doc.file_id)

    properties = await get_file_properties(doc_file, "Document", doc.file_name)
    success = await save_to_notion(properties)

    if success:
        await update.message.reply_text(f"Document '{doc.file_name}' sauvegardé dans Notion !")
    else:
        await update.message.reply_text("Oups ! Une erreur s'est produite lors de la sauvegarde dans Notion.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log les erreurs causées par les Updates."""
    logger.error(f"Exception lors du traitement d'une mise à jour: {context.error}", exc_info=context.error)
    # Optionnel: Informer l'utilisateur qu'une erreur s'est produite
    if isinstance(update, Update) and update.effective_message:
         try:
             await update.effective_message.reply_text("Désolé, une erreur interne est survenue.")
         except Exception as e:
             logger.error(f"Impossible d'envoyer un message d'erreur à l'utilisateur: {e}")


# --- Fonction Principale ---

def main() -> None:
    """Démarre le bot."""
    # Crée l'Application et lui passe le token du bot.
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Ajoute les gestionnaires
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document)) # Prend tous types de documents

    # Gestionnaire d'erreurs (important !)
    application.add_error_handler(error_handler)

    # Démarre le Bot en mode polling (vérifie régulièrement les nouveaux messages)
    logger.info("Démarrage du bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
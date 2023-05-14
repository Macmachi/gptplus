# -*- coding: utf-8 -*-
'''
#
# PROJECT: GPTPLUS
# AUTHOR: Arnaud (https://github.com/Macmachi)
# VERSION: 1.1.1
# FULLY SUPPORTED LANGUAGES: FRENCH, ENGLISH
# FEATURES : All GPT4 model capabilities, real time weather information for a city, current news for USA, France, Switzerland, image generations with DALL·E 2 
# TELEGRAM COMMANDS : /start, /help, /aide, /chatid, /reset
#
# DOCUMENTATION API :
# Documentation about OPENAI API : https://platform.openai.com/overview 
# Prices using OPENAI API : https://openai.com/pricing#language-models
#
# NICE-TO-HAVE FEATURES:
* Implementation of OpenAI's tiktoken to count the used tokens: https://github.com/openai/tiktoken + logs the price of the generated images too
'''
import asyncio
import openai
import json
import httpx
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils.exceptions import RetryAfter, TelegramAPIError
from aiohttp import ClientSession
from typing import Tuple, Optional
import re
import datetime
import configparser

config = configparser.ConfigParser()
# Please edit the INI file with personal information (check comments in INI file)
config.read('config.ini')
# KEYs from the INI file
API_KEY = config['KEYS']['OPENAI_API_KEY']
openai.api_key = API_KEY
TELEGRAM_BOT_TOKEN = config['KEYS']['TELEGRAM_BOT_TOKEN']
CHAT_ID = config['KEYS']['CHAT_ID']
NEWSAPI_KEY = config['KEYS']['NEWSAPI_KEY']

# function to display a log message with a time stamp
def log_message(message):
    with open("log-gptplus.txt", "a", encoding='utf-8') as log_file:
        log_file.write(f"{datetime.datetime.now()} - {message}\n")

def save_conversation_history(user_id, user_messages, filename="conversation_history.json"):
    try:
        with open(filename, "a+", encoding="utf-8") as f:  
            # rewind the file to the beginning to read its content
            f.seek(0)  
            try:
                all_conversations = json.load(f)
            except json.JSONDecodeError:
                log_message(f"The file {filename} is empty or corrupted. Creation of a new dictionary.")
                all_conversations = {}
    except Exception as e:
        log_message(f"Error while recording conversations : {e}")
        # add this line to handle unexpected errors
        all_conversations = {}  

    # memory management - keeps only the last 6 messages (3 from the user and 3 from the assistant)
    user_messages = user_messages[-6:]  
    all_conversations[str(user_id)] = user_messages

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_conversations, f, ensure_ascii=False, indent=4)

def load_conversation_history(user_id, filename="conversation_history.json"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            all_conversations = json.load(f)
            return all_conversations.get(str(user_id), [])
    except FileNotFoundError:
        log_message(f"Erreur : Fichier {filename} introuvable")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)
        return []
    
def reset_conversation_history(user_id, filename="conversation_history.json"):
    try:
        with open(filename, "r+", encoding="utf-8") as f:
            all_conversations = json.load(f)
            if str(user_id) in all_conversations:
                all_conversations[str(user_id)] = []
                f.seek(0)
                json.dump(all_conversations, f, ensure_ascii=False, indent=4)
                f.truncate()
                return True
            else:
                return False
    except FileNotFoundError:
        log_message(f"Error: File {filename} not found")
        return False
    
async def get_crypto_infos(crypto_id, crypto_name):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.coinpaprika.com/v1/tickers/{crypto_id}")
            response.raise_for_status()
            data = response.json()
            crypto_infos = data
            log_message(f"Successful recovery of information on the crypto {crypto_name}: {data}")
            return crypto_infos
    except (httpx.HTTPError, KeyError):
        log_message(f"Error while retrieving crypto info")
        return None

async def get_news_headlines(news_category: str):
    if not NEWSAPI_KEY:
        log_message(f"A key in the ini file for the news api was NOT detected")
    else:
        log_message(f"A key in the ini file for the news api has been detected")
    if news_category == "monde":
        # Modifier l'URL pour récupérer les actualités mondiales
        url = f"https://newsapi.org/v2/top-headlines?country=us&apiKey={NEWSAPI_KEY}"
    elif news_category == "france":
        url = f"https://newsapi.org/v2/top-headlines?country=fr&apiKey={NEWSAPI_KEY}"
    elif news_category == "suisse":
        url = f"https://newsapi.org/v2/top-headlines?country=ch&apiKey={NEWSAPI_KEY}"
    elif news_category == "usa":
        url = f"https://newsapi.org/v2/top-headlines?country=us&apiKey={NEWSAPI_KEY}"
    else:
        url = f"https://newsapi.org/v2/top-headlines?language=fr&apiKey={NEWSAPI_KEY}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                
        headlines = []
        for article in data["articles"][:10]:
            title = article["title"]
            headlines.append(f"{title}\n")
            
        log_message(f"Successful news retrieval for the category {news_category}: {len(headlines)} titles")
        return headlines
    
    except Exception as e:
        log_message(f"Error when retrieving news : {e}")        
        return None

async def get_city_coordinates(city_name: str, language: str) -> Optional[Tuple[float, float]]:
    api_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_name}&count=1&language={language}&format=json"
    try:
        async with ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    log_message(f"API error, status code: {response.status}") 
                    raise Exception(f"API error, status code: {response.status}")
                data = await response.json()

        if data and data['results']:
            latitude = data['results'][0]['latitude']
            longitude = data['results'][0]['longitude']
            return latitude, longitude

    except Exception as e:
        log_message(f"Error retrieving city coordinates: {e}")        
        return None

async def get_weather_data(latitude: float, longitude: float) -> Optional[dict]:
    api_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=temperature_2m,relativehumidity_2m,precipitation,surface_pressure,cloudcover,windspeed_10m&models=best_match&daily=sunrise,sunset&forecast_days=3&timezone=Europe%2FBerlin"
       
    try:
        async with ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    log_message(f"API error, status code: {response.status}") 
                    raise Exception(f"API error, status code: {response.status}")
                data = await response.json()
                weather_data = data
                return weather_data

    except Exception as e:
        log_message(f"Error retrieving weather data: {e}")        
        return None

async def get_gpt4_response(prompt, user_messages, bot, chat_id, authorized_chat_id=None, external_data=None):
    # log the unauthorized chat id that tries to call your bot
    if chat_id != authorized_chat_id:
        await bot.send_message(chat_id, f"Unauthorized access from the user (your chat ID: {chat_id}). You can use my telegram bot with my code : https://github.com/Macmachi/gptplus/")
        log_message(f"Unauthorized access of the user with the chat_id {chat_id}")
        return

    crypto_data = [
        {"name": "bitcoin", "id": "btc-bitcoin"},
        {"name": "ethereum", "id": "eth-ethereum"},
        {"name": "avax", "id": "avax-avalanche"},
        {"name": "monero", "id": "xmr-monero"},
    ]

    for crypto in crypto_data:
        if crypto["name"] in prompt.lower():
            crypto_infos = await get_crypto_infos(crypto["id"], crypto["name"])
            log_message(f"Successful retrieval of crypto prices from get_gpt4_response")

            if crypto["name"] is not None:
                external_data = f"The crypto information: {crypto_infos} as of the current date and time, {datetime.datetime.now()}, that you need to interpret based on the question in this prompt: {prompt}"

    # news in French
    if "actualités" in prompt.lower() or "l'actualité" in prompt.lower() or "nouvelles" in prompt.lower() or "infos" in prompt.lower() or "informations" in prompt.lower():
        if "monde" in prompt.lower():
            news_category = "monde"
        elif "france" in prompt.lower():
            news_category = "france"
        elif "française" in prompt.lower():
            news_category = "france"              
        elif "suisse" in prompt.lower():
            news_category = "suisse"                
        elif "usa" in prompt.lower():
            news_category = "usa"             
        else:
            news_category = "monde"
        
        news_headlines = await get_news_headlines(news_category)
        log_message(f"Succès de la récupération des headlines depuis get_gpt4_response")
        if news_headlines:
            external_data = f"Voici les actualités aujourd'hui à {datetime.datetime.now()} à traduire en français (si elles ne sont pas en français) pour ({news_category}) : \n\n" + "".join(news_headlines)

    # news in English 
    if "news" in prompt.lower() or "new" in prompt.lower() or "headlines" in prompt.lower() :
        if "world" in prompt.lower():
            news_category = "monde"
        elif "france" in prompt.lower():
            news_category = "france"
        elif "french" in prompt.lower():
            news_category = "france"    
        elif "switzerland" in prompt.lower():
            news_category = "suisse"  
        elif "swiss" in prompt.lower():
            news_category = "suisse"       
        elif "usa" in prompt.lower():
            news_category = "usa"             
        else:
            news_category = "monde"

        news_headlines = None
        if news_category:
            log_message(f"Successful recovery of the category {news_category}")
            news_headlines = await get_news_headlines(news_category)
            if news_headlines is None:
                log_message(f"Error while retrieving news for the category {news_category}")
            else:
                log_message(f"Successful retrieval of headlines from get_news_headlines")
        if news_headlines:
            external_data = f"Here are the news today at {datetime.datetime.now()} to be translated into english (if they are not in english) for ({news_category}) : \n\n" + "".join(news_headlines)

    # weather in French
    keywords = ["temps", "météo", "température", "soleil", "uv", "vent", "pluie", "humidité", "prévision"]
    if any(keyword in prompt.lower() for keyword in keywords):
        city_match = re.search(r"\b(?:météo|temps|température|prévision|soleil|uv|vent|pluie|humidité)\s+(?:à|pour|a)?\s+(\w+)", prompt.lower())
        if city_match:
            city_name = city_match.group(1)
            language = 'fr'
            coordinates = await get_city_coordinates(city_name, language)
            if coordinates:
                weather_data = await get_weather_data(*coordinates)
                log_message(f"Successful retrieval of weather data from get_gpt4_response")
                if weather_data:
                    external_data = f"Voici les données météo pour la ville de {city_name.capitalize()}, les données que tu dois interpréter selon la question de l'utilisateur : {weather_data} sachant que la date et l'heure actuel est {datetime.datetime.now()}."

    # weather in English 
    keywords = ["weather","temperature","forecast","sun","uv","wind","rain","humidity"]
    if any(keyword in prompt.lower() for keyword in keywords):
        city_match = re.search(r"\b(?:weather|temperature|forecast|sun|uv|wind|rain|humidity)\s+(?:à|pour|in|of)?\s+(\w+)", prompt.lower())
        if city_match:
            city_name = city_match.group(1)
            language = 'en'
            coordinates = await get_city_coordinates(city_name, language)
            if coordinates:
                weather_data = await get_weather_data(*coordinates)
                log_message(f"Successful retrieval of weather data from get_gpt4_response")
                if weather_data:
                    external_data = f"Here are the weather data for the city of {city_name.capitalize()}, the data you need to interpret according to the user's question: {weather_data}, knowing that the current date and time is {datetime.datetime.now()}."

    previous_messages = "\n".join([f"{msg['role']}: {msg['content']}" for msg in user_messages])

    if external_data:
        prompt_with_history = f"Voici les messages précédents :\n{previous_messages}\nMa question (adapte toi à la langue utilisée pour ma question) : {prompt}\nLa réponse actuelle de l'API que tu dois reformuler pour me répondre : {external_data}"
    else:
        prompt_with_history = f"Voici les messages précédents :\n{previous_messages}\nMa question (adapte toi à la langue utilisée pour ma question) : {prompt}"

    log_message(f"Updated prompt with external data: {prompt_with_history}")
    
    try:
        # Create a chat completion request with stream=True.
        response = openai.ChatCompletion.create(
            model='gpt-4',  
            messages=[{"role": "user", "content": prompt_with_history}],
            max_tokens=2000,
            n=1,
            temperature=0.5,
            stream=True,
        )

        # Iterate through the response chunks
        message = ""
        buffer = ""
        for chunk in response:
            if "choices" in chunk and len(chunk["choices"]) > 0:  # type: ignore
                delta = chunk["choices"][0]["delta"]  # type: ignore
                if "content" in delta:
                    content = delta["content"]
                    message += content
                    buffer += content
                    
                    if "." in buffer:
                        sentences = re.split(r'(?<!\d)\.(?=\s|$)', buffer)
                        buffer = sentences.pop()
                    
                        for sentence in sentences:
                            await bot.send_message(chat_id=chat_id, text=sentence, disable_web_page_preview=True)

        if buffer:
            await bot.send_message(chat_id=chat_id, text=buffer, disable_web_page_preview=True)

        return message
    
    except Exception as e:
        error_message = "Désolé, une erreur s'est produite lors du traitement de votre demande. Veuillez réessayer plus tard."
        log_message(f"Erreur lors du traitement du message : {e}")
        await bot.send_message(chat_id=chat_id, text=error_message)
        log_message(f"Message d'erreur envoyé à l'utilisateur {chat_id} : {error_message}")

def generate_image(prompt):
    response = openai.Image.create(
      prompt=prompt,
      n=1,
      size="1024x1024"
    )
    image_url = response['data'][0]['url'] # type: ignore
    return image_url

async def start(message: types.Message):
    await message.reply("""
Hi there! I'm a bot that uses the OpenAI GPT-4 API. Ask me questions, and I'll do my best to answer them! 
Access help with the command /help.

Salut! Je suis un bot qui utilise l'API OpenAI GPT-4.
Posez-moi des questions et je ferai de mon mieux pour vous répondre!
Accède à l'aide avec la commande 
/aide

My Github : https://github.com/Macmachi/gptplus/
My XMR wallet if you like my telegram bot : 47aRxaose3a6Uoi8aEo6sDPz3wiqfTePt725zDbgocNuBFSBSXmZNSKUda6YVipRMC9r6N8mD99QjFNDvz9wYGmqHUoMHbR  
""")
def get_chat_id(message: types.Message):
    return message.chat.id

async def chatid_command(message: types.Message):
    chat_id = get_chat_id(message)
    await message.reply(f"The ID of this chat is {chat_id}")

async def reset_command(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    # security measures are implemented to allow only the authorized chat ID to receive messages and use your API key
    authorized_chat_id = int(CHAT_ID)
    if message.chat.id != authorized_chat_id:
        await bot.send_message(message.chat.id, f"Unauthorized access from the user (your chat ID: {message.chat.id}). You can use my telegram bot with my code : https://github.com/Macmachi/gptplus/")
        log_message(f"Unauthorized access attempt from chat ID: {message.chat.id}")
        return
    result = reset_conversation_history(user_id)
    if result:
        await message.reply("Conversation history reset successfully.")
    else:
        await message.reply("Could not reset conversation history.")

async def aide_command(message: types.Message):
    help_message = """
Voici les commandes que vous pouvez utiliser :
/start - Démarrer la conversation avec le bot
/chatid - Récupérer l'id de votre chat
/reset - Reset la mémoire du bot
/aide - Afficher ce message d'aide\n\n 
Informations récupérées en temps réel\n  
[METEO] Demander des informations sur la météo actuelle ou dans les 3 prochains jours.
En plus de votre question, il faut utiliser ces mots clés à choix :\n [météo|temps|température|prévision|soleil|uv|vent|pluie|humidité] + [à|a|pour] + [NomVille])\n 
[ACTUALITE] Demander des informations sur l'actualité
Il faut utiliser ces mots clés à choix : [actualités|l'actualité|nouvelles|infos|informations] + [monde|usa|suisse|france])\n 
[CRYPTOS] Demander des informations sur les cryptos
En plus de votre question, il faut utiliser ces mots clés à choix : bitcoin|ethereum|avax|monero)\n
[IMAGES] Génère des images
Tapez [génère] + suivi de ce que que vous souhaitez générer\n
Mon Github : https://github.com/Macmachi/gptplus/
Mon wallet XMR si tu aimes mon bot telegram : 47aRxaose3a6Uoi8aEo6sDPz3wiqfTePt725zDbgocNuBFSBSXmZNSKUda6YVipRMC9r6N8mD99QjFNDvz9wYGmqHUoMHbR
    """
    await message.reply(help_message)

async def help_command(message: types.Message):
    help_message = """
Here are the commands you can use:
/start - Start the conversation with the bot
/chatid - Retrieve your chat ID
/reset - Reset the bot's memory
/help - Display this help message\n\n 
Real-time information retrieval:
[WEATHER] Request information about the current weather or the next 3 days.
In addition to your question, use these keywords:\n   [weather|temperature|forecast|sun|uv|wind|rain|humidity] + [in|for] + [CityName]\n  
[NEWS] Request information about the news.
Use these keywords: [news|headlines] + [world|usa|switzerland||france|french]\n  
[CRYPTOS] Request information about cryptocurrencies.
In addition to your question, use these optional keywords: [bitcoin|ethereum|avax|monero]\n
[CRYPTOS] Request information about cryptocurrencies.
In addition to your question, use these optional keywords: [bitcoin|ethereum|avax|monero]\n
[IMAGES] Generates images
Type [generate] + followed by what you want to generate\n
My Github : https://github.com/Macmachi/gptplus/
My XMR wallet if you like my telegram bot : 47aRxaose3a6Uoi8aEo6sDPz3wiqfTePt725zDbgocNuBFSBSXmZNSKUda6YVipRMC9r6N8mD99QjFNDvz9wYGmqHUoMHbR  
    """
    await message.reply(help_message)

async def handle_message(message: types.Message, bot: Bot):
    try:
        # security measures are implemented to allow only the authorized chat ID to receive messages and use your API key
        user_id = message.from_user.id
        authorized_chat_id = int(CHAT_ID)
        if message.chat.id != authorized_chat_id:
            await bot.send_message(message.chat.id, f"Unauthorized access from the user (your chat ID: {message.chat.id}). You can use my telegram bot with my code : https://github.com/Macmachi/gptplus/")
            log_message(f"Unauthorized access attempt from chat ID: {message.chat.id}")
            return

        user_messages = load_conversation_history(user_id)

        prompt = message.text
        log_message(f"value of the prompt coming from Telegram': {prompt}")
        # Si les mots "generate" ou "génère" sont présents dans l'entrée de l'utilisateur
        if re.search(r'\b(generate|génère)\b', prompt, re.IGNORECASE):
            # Extraire le texte après "generate" ou "génère" pour l'utiliser comme prompt
            prompt = re.split(r'\b(generate|génère)\b', prompt, flags=re.IGNORECASE)[-1].strip()
            # Générer une image et renvoyer l'URL de l'image
            image_url = generate_image(prompt)
            await bot.send_photo(chat_id=message.chat.id, photo=image_url)
        else:
            response = ""
            response = await get_gpt4_response(prompt, user_messages, bot, message.chat.id, authorized_chat_id)
            log_message(f"Réponse de l'api d'OpenAI ': {response}")
            # we format the unchanged user prompt
            user_messages.append({"role": "user", "content": prompt})
            # we format the response from OpenAI
            user_messages.append({"role": "gpt4", "content": response})
            # we save both of them in the conversation history
            save_conversation_history(user_id, user_messages)

    except RetryAfter as exception:
        log_message(f"Exception {exception} caught for update {message}. Retrying after {exception.timeout} seconds.")
        await asyncio.sleep(exception.timeout)
        await handle_message(message, bot)

async def on_telegram_api_error(exception: TelegramAPIError, bot: Bot, update: types.Update):
    log_message(f"Exception {exception} caught for update {update}. Skipping this update.")
    
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(bot)
    dp.middleware.setup(LoggingMiddleware())
    dp.register_message_handler(start, commands=['start'])
    dp.register_message_handler(aide_command, commands=['aide'])
    dp.register_message_handler(help_command, commands=['help'])
    dp.register_message_handler(chatid_command, commands=['chatid'])
    dp.register_message_handler(lambda message: reset_command(message, bot), commands=['reset'])
    dp.register_message_handler(lambda message: handle_message(message, bot), content_types=['text'])
    # add these lines to save the error handlers
    dp.register_errors_handler(on_telegram_api_error, exception=TelegramAPIError)
    # start polling
    await dp.start_polling()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"
)
model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

print(f"🔄 Probando chat con el modelo [{model}]...")

response = client.chat.completions.create(
    model=model,
    messages=[
        {
            "role": "user",
            "content": "Hola, confirma en una sola frase si estás listo para atender a los clientes de Globex.",
        }
    ],
    temperature=0.3,
)

print("\n✅ RESPUESTA DEL MODELO:")
print(response.choices[0].message.content)

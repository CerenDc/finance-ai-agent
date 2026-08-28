import json

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage

from app.tools.finance_tools import (
    get_customers,
    get_invoices,
    get_overdue_invoices,
)

load_dotenv()


llm = ChatOpenAI(
    model="gpt-4.1-mini",
    temperature=0
)


tools = [
    get_customers,
    get_invoices,
    get_overdue_invoices
]


llm_with_tools = llm.bind_tools(tools)


tool_map = {
    tool.name: tool
    for tool in tools
}


def run_agent(question: str):

    messages = [
        HumanMessage(content=question)
    ]

    # Maximum 5 étapes pour éviter une boucle infinie
    for step in range(5):

        response = llm_with_tools.invoke(messages)

        messages.append(response)

        # Si le modèle ne demande plus de tool,
        # on a notre réponse finale
        if not response.tool_calls:
            return response.content

        # Exécution des tools demandés
        for tool_call in response.tool_calls:

            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            print(
                f"\n🔧 Tool appelé : {tool_name}"
            )
            print(
                f"📥 Arguments : {tool_args}"
            )

            tool = tool_map[tool_name]

            result = tool.invoke(tool_args)

            print(
                f"📤 Résultat : {result}"
            )

            messages.append(
                ToolMessage(
                    content=json.dumps(
                        result,
                        ensure_ascii=False
                    ),
                    tool_call_id=tool_call["id"]
                )
            )

    return "Nombre maximum d'étapes atteint."


if __name__ == "__main__":

    question = input(
        "\n💬 Pose ta question : "
    )

    answer = run_agent(question)

    print("\n🤖 Réponse finale :")
    print(answer)
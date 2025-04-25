import chainlit as cl
import json
from typing import Any, Callable, Set, Dict, List, Optional
import os, time
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.projects.models import FunctionTool, ToolSet, AzureAISearchTool, AzureAISearchQueryType
from azure.ai.projects.models import FunctionTool, ToolSet, RequiredFunctionToolCall, SubmitToolOutputsAction, ToolOutput


# Define the function to fetch weather information
def fetch_weather(location: str) -> str:
    """
    Fetches the weather information for the specified location.

    :param location (str): The location to fetch weather for.
    :return: Weather information as a JSON string.
    :rtype: str
    """
    # In a real-world scenario, you'd integrate with a weather API.
    # Here, we'll mock the response.
    mock_weather_data = {
        "New York": "Sunny, 25°C", 
        "London": "Cloudy, 18°C", 
        "Tokyo": "Rainy, 22°C"
    }
    weather = mock_weather_data.get(location, "Weather data not available for this location.")
    weather_json = json.dumps({"weather": weather})
    return weather_json

# Define the function to fetch restaurant information
def fetch_restaurant(location: str) -> str:
    """
    Fetches the restaurant information for the specified location.

    :param location (str): The location to fetch the restaurant for.
    :return: Restaurant information as a JSON string.
    :rtype: str
    """
    # In a real-world scenario, you'd integrate with a restaurant API.
    # Here, we'll mock the response.
    mock_restaurant_data = {
        "New York": "Tatiana by Kwame Onwuachi, Katz’s Delicatessen, Peter Luger Steakhouse, Sylvia's, Nathan's Famous", 
        "London": "St. JOHN, Señor Ceviche, Gloria and Circolo Popolare, Normah's, Bouchon Racine", 
        "Tokyo": "Chanko & Wanko Restaurant Asakusa Sumo Club, Sky Restaurant 634 Musashi, Ichiran, Shibuya, Rokkasen Otakibashiidori, Hakushu - Kobe Teppanyaki"
    }
    restaurant = mock_restaurant_data.get(location, "Restaurant data not available for this location.")
    restaurant_json = json.dumps({"restaurant": restaurant})
    return restaurant_json

# Define the function to fetch budget information
def fetch_budget() -> str:
    """
    Fetches the budget information for the specified location.
    :return: budget information as a JSON string.
    :rtype: str
    """
    # In a real-world scenario, you'd integrate with a another API.
    # Here, we'll mock the response.
    mock_budget_data = {
        "New York": """
            Budget Travelers: Around $121 per day. This includes staying in hostels, eating at budget restaurants, and using public transportation.
            Mid-Range Travelers: Approximately $324 per day. This covers mid-range hotels, dining at average restaurants, and some paid attractions.
            Luxury Travelers: About $923 per day. This includes luxury hotels, fine dining, and private transportation.
        """, 
        "London": """
            Budget Travelers: Around $75 per day. This includes staying in hostels, cooking your own meals, and using public transport.
            Mid-Range Travelers: Approximately $195 per day. This covers mid-range hotels, dining at average restaurants, and some paid attractions.
            Luxury Travelers: About $517 per day. This includes luxury hotels, fine dining, and private transportation.
        """, 
        "Tokyo": """
            Budget Travelers: Around $100 per day. This includes staying in hostels, eating at budget restaurants, and using public transportation.
            Mid-Range Travelers: Approximately $286 per day. This covers mid-range hotels, dining at average restaurants, and some paid attractions.
            Luxury Travelers: About $908 per day. This includes luxury hotels, fine dining, and private transportation.
        """
    }
    budget_json = json.dumps({"budget": mock_budget_data})
    return budget_json

# Statically defined user functions for fast reference
user_functions: Set[Callable[..., Any]] = {
    fetch_weather, fetch_restaurant, fetch_budget
}

def reformat_citations(content_block):
    annotations = content_block.get("annotations", [])
    paragraph = content_block["value"]
    
    # Map citation_title -> set of placeholders
    citation_map = {}
    for annotation in annotations:
        if annotation["type"] == "url_citation":
            placeholder_text = annotation["text"]
            citation_title = annotation["url_citation"]["title"]
            citation_map.setdefault(citation_title, set()).add(placeholder_text)

    # Remove all placeholders from the paragraph
    for placeholders in citation_map.values():
        for placeholder_text in placeholders:
            paragraph = paragraph.replace(placeholder_text, "")

    # If there's at least one citation, append "Source: ..." at the end
    if citation_map:
        sources = ", ".join(citation_map.keys())
        paragraph = paragraph.strip() + f" Source: {sources}"

    return paragraph

# Define the function to run the agent
def run_agent(user_input, project_client, thread, agent): 

    functions = FunctionTool(user_functions)

    # Add a message to the thread  
    message = project_client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=user_input,
    )
    print(f"Created message, ID: {message.id}")

    # Step 4: Run the agent
    run = project_client.agents.create_run(thread_id=thread.id, agent_id=agent.id)
    print(f"Created run, ID: {run.id}")

    # Step 5: Check the Run Status
    while run.status in ["queued", "in_progress", "requires_action"]:
        time.sleep(1)
        run = project_client.agents.get_run(thread_id=thread.id, run_id=run.id)

        # Print the current status of the run
        print(f"Current run status: {run.status}")

        if run.status == "requires_action" and isinstance(run.required_action, SubmitToolOutputsAction):
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            if not tool_calls:
                print("No tool calls provided - cancelling run")
                project_client.agents.cancel_run(thread_id=thread.id, run_id=run.id)
                break

            tool_outputs = []
            for tool_call in tool_calls:
                if isinstance(tool_call, RequiredFunctionToolCall):
                    try:
                        print(f"Executing tool call: {tool_call}")
                        output = functions.execute(tool_call)
                        tool_outputs.append(
                            ToolOutput(
                                tool_call_id=tool_call.id,
                                output=output,
                            )
                        )
                    except Exception as e:
                        print(f"Error executing tool_call {tool_call.id}: {e}")

            print(f"Tool outputs: {tool_outputs}")
            if tool_outputs:
                project_client.agents.submit_tool_outputs_to_run(
                    thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs
                )
    
        if run.status == "failed":
            print(f"Run failed: {run.last_error}")

        # Step 6: Display the Agent's Response
        elif run.status == 'completed':
            # Fetch all messages in the thread
            messages = project_client.agents.list_messages(thread_id=thread.id)
            if messages.data:
                agent_message = messages.data[0]  # Get the last assistant message
                content_block = agent_message.content[0].text

                # Check if there are annotations before reformatting the response
                if content_block.get("annotations"):
                    # Reformat the response to replace placeholders with citation titles
                    agent_response = reformat_citations(content_block)
                else:
                    agent_response = content_block["value"]

                print(f"Agent Response: {agent_response}")
            else:
                print("No messages found.")
    
    return agent_response

# Define the function to delete the agent
def delete_agent(project_client, agent):
    # Delete the agent when done
    project_client.agents.delete_agent(agent.id)
    print("Deleted agent")
    

@cl.on_chat_start
def on_chat_start():
    
    global project_client
    global agent
    global thread

    project_connection_string = os.getenv("PROJECT_CONNECTION_STRING")
    # Create an Azure AI Client from a connection string, copied from your Azure AI Foundry project.    
    project_client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(),
        conn_str=project_connection_string,
    )

    # Initialize agent AI search tool and add the search index connection ID and index name
    connection_id = os.getenv("PROJECT_CONNECTION_ID_AZURE_AI_SEARCH")
    index_name = "travel-product-index"
    ai_search = AzureAISearchTool(
        index_connection_id=connection_id, 
        index_name=index_name,
        query_type=AzureAISearchQueryType.VECTOR_SEMANTIC_HYBRID,
        top_k=5,
    )

    # Initialize agent toolset with user functions
    functions = FunctionTool(user_functions)
    toolset = ToolSet()
    toolset.add(functions)
    toolset.add(ai_search)
    
    # Create a new agent with the toolset
    agent = project_client.agents.create_agent(
        model="gpt-4o-mini", 
        name="my-chainlit-agent", 
        instructions="""
            You are an AI Travel Agent. 
            You will answer questions about travel based on the tools provided.
            When asked questions about products, you will use the Azure AI Search tool to find relevant products.
        """, 
        toolset=toolset
    )

    print(f"Created agent, ID: {agent.id}")

    # Create a new thread for the agent
    thread = project_client.agents.create_thread()
    print(f"Created thread, ID: {thread.id}")
    
    print("A new chat session has started!")

@cl.on_message
async def main(message: cl.Message):

    # Call the agent with the user's message
    agent_response = run_agent(message.content, project_client, thread, agent)
    
    # Send a response back to the user
    await cl.Message(
        content=agent_response,
    ).send()

@cl.on_chat_end
def on_chat_end():
    # Delete the agent when done
    delete_agent(project_client, agent)
    print("The user disconnected!")

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Weather Queries",
            message="What is the weather like in New York?",
            icon="/public/weather.svg",
            ),

        cl.Starter(
            label="Restaurant Recommendations",
            message="What are some good restaurants in London?",
            icon="/public/food.svg",
            ),
        cl.Starter(
            label="Budget Information",
            message="How much does it cost to travel to Tokyo?",
            icon="/public/money.svg",
            ),
        cl.Starter(
            label="Budget Recommendations",
            message="If I have a budget of $300 for 4 days, where should I travel?",
            icon="/public/calculator.svg",
            ),
        cl.Starter(
            label="Suitcase Products",
            message="What suitcases do you have?",
            icon="/public/suitcase.svg",
            ),
        cl.Starter(
            label="Handcarry Bags",
            message="Do you have any bags available?",
            icon="/public/briefcase.svg",
            )
        ]
"""Nourish Agent — conversational nutrition coach built on LangGraph.

Layers on top of the deterministic Nourish engine:
  config.py         .env loading (Groq + Tavily keys)
  profile.py        persistent user health profile + answer parsing
  vectorless.py     vector-less RAG: direct fuzzy lookup over the SQLite stores
  vectorstore.py    traditional RAG: Chroma index over dishes + IFCT 2017 PDF
  dietchart.py      grounded day-plan generator from the profile + dish DB
  agent_history.py  friendly log of dishes the user asked about
  tools.py          LangChain tools the agent can call
  graph.py          the LangGraph state machine (onboarding interrupts + chat)
"""

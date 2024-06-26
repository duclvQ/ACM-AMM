#!/usr/bin/env python3
# -*- coding: utf-8
# ----------------------------------------------------------------------------
# Created By  : Linh Vo Van
# Organization: ACM Lab
# Created Date: 2024/03/15
# version ='1.0'
# Description:
# Automatic Meeting Assistant
# This application leverages language models and a knowledge base to provide
# comprehensive responses to user queries within a chat interface.

# Key Features:
# - Knowledge Base Creation: Users can upload documents to a knowledge base.
# - Document Retrieval: The application retrieves relevant documents from the
#   knowledge base based on user queries.
# - LLM Response Generation: It uses a large language model to generate
#   informative responses, considering both the user's query and retrieved
#   context.

# External Libraries:
# - Streamlit: Provides a user-friendly web interface.
# - langchain: Facilitates working with language models and vector stores.
# - OPENAI_AI_KEY Endpoints: Connects to NVIDIA's AI models for embedding and response generation.

# Environment Variables:
# - OPENAI_AI_KEY: Required for accessing OPENAI_AI_KEY services.

# Component Structure:
# 1. Knowledge Base Management: Handles file uploads and storage.
# 2. Embedding Model and LLM: Loads and initializes language models and embedders.
# 3. Vector Database Store: Creates and manages a FAISS vector store for document retrieval.
# 4. LLM Response Generation and Chat: Manages user interaction, retrieves relevant documents,
#    generates responses using the LLM, and presents conversations in a chat interface.
# ---------------------------------------------------------------------------

from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser

from langchain.document_loaders import DirectoryLoader

from langchain.chains import LLMChain
from langchain_community.llms import HuggingFaceHub, HuggingFaceEndpoint
from langchain_community.llms.huggingface_pipeline import HuggingFacePipeline
from langchain_community.embeddings import HuggingFaceHubEmbeddings

import os
import streamlit as st

from modules.utils import upload_file, store_vector
from modules.audio2dia import Audio2Dia
from modules.prompt import *

# ========================================
# Document Loader
# ========================================
st.set_page_config(layout="wide")

DOCS_DIR_PATH = "database/uploaded_docs"
AUDIO_DIR_PATH = "database/uploaded_audios"

uploaded_files, submitted = upload_file(DOCS_DIR_PATH, AUDIO_DIR_PATH)

#  Audio to Dialogue Model
if uploaded_files and submitted:
    for uploaded_file in uploaded_files:
        print(uploaded_file.name[:-3])
        model_audio = Audio2Dia(name_model='large-v2',
                                batch_size=16,
                                compute_type="float16",
                                device="cuda",
                                device_index=2)
        model_audio.generate(os.path.join(AUDIO_DIR_PATH, uploaded_file.name),
                             os.path.join(DOCS_DIR_PATH, f"{uploaded_file.name[:-3]}txt"))
# ========================================
#  Embedding Model and LLM
# ========================================

llm = HuggingFacePipeline.from_model_id(
    model_id="microsoft/Phi-3-mini-128k-instruct",
    task="text-generation",
    device=2,
    model_kwargs={
        "top_k": 30,
        "temperature": 0.1,
        "repetition_penalty": 1.03,
        'trust_remote_code':True
    },
    pipeline_kwargs={
        "max_new_tokens": 512,
    }
)

document_embedder = HuggingFaceHubEmbeddings()
# ========================================
# Vector Database Store
# ========================================


with st.sidebar:
    # Option for using an existing vector store
    use_existing_vector_store = st.radio("Use existing vector store if available", [
                                         "Yes", "No"], horizontal=True)

# Path to the vector store file
vector_store_path = "database/vectorstore/vectorstore.pkl"

# Load raw documents from the directory
raw_documents = DirectoryLoader(os.path.abspath(DOCS_DIR_PATH)).load()


# Check for existing vector store file
vector_store_exists = os.path.exists(vector_store_path)
# vectorstore = None
vectorstore = store_vector(vector_store_path, raw_documents,
             use_existing_vector_store, document_embedder)

# ========================================
# LLM Response Generation and Chat
# ========================================

st.subheader("Automatic Meeting Assistant")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])




# ========================================
user_input = st.chat_input("Can you tell me what is known for?")

# ===== Prompt pipeline =====
# parser actually doesn’t block the streaming output from the model, and instead processes each chunk individuall
chain = llm | StrOutputParser()
llm_chain_seeking = LLMChain(prompt=prompt_seeking, llm=llm)
chain_seeking = prompt_seeking | llm | StrOutputParser()
chain_indetify = prompt_indetify | llm | StrOutputParser()
chain_finding = prompt_finding | llm | StrOutputParser()
chain_suggestion = prompt_suggestion | llm | StrOutputParser()

chain_rephase = prompt_rephase | llm | StrOutputParser()

if user_input and vectorstore != None:
    st.session_state.messages.append({"role": "user", "content": user_input})
    retriever = vectorstore.as_retriever()
    docs = retriever.get_relevant_documents(user_input)
    with st.chat_message("user"):
        st.markdown(user_input)
    
    context = ""
    for doc in docs:
        context += doc.page_content + "\n\n"

    # generate specific prompt
    augmented_user_input = "Context: " + context + \
        "\n\nQuestion: " + user_input + "\n"
    
    user_seeking = llm_chain_seeking.run(user_input)

    validate_information = chain_indetify.invoke({"user_prompt": user_input, "user_intent": {user_seeking}})

    extra_information = chain_finding.invoke({"user_prompt": user_input, "user_intent": {user_seeking}})

    susgestion_format = chain_suggestion.invoke(({
        "missing_information": extra_information
    }))
    print(susgestion_format)
    # the message will have a default bot icon with name "assistant"
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        # Due to each resposne is generate one words so it need to stored in one
        # sync stream and async astream
        for response in chain_rephase.stream({"input": user_input, "context": {context}}):
            full_response += response
            message_placeholder.markdown(full_response + "▌")
        message_placeholder.markdown(full_response)
    st.session_state.messages.append(
        {"role": "assistant", "content": full_response})

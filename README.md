# Program Description

This Python script is a desktop application for translating `.srt` subtitle files. It provides a user-friendly graphical interface (GUI) to translate subtitles from English into a wide variety of other languages by leveraging local Large Language Models (LLMs) through the Ollama API.

The application is designed to be a private and cost-effective alternative to cloud-based translation services. Users can select one or more `.srt` files, or an entire folder for batch processing.

## Key Features

- **Local Translation:** Uses a running Ollama instance to perform translations locally, ensuring data privacy and no API costs.  
- **Graphical User Interface:** Built with PyQt6, it offers an intuitive interface for selecting files, models, and translation options.  
- **Batch Processing:** Translate a single `.srt` file or an entire folder of subtitle files at once.  
- **Model Selection:** Automatically detects and allows you to choose from any of the language models you have installed in Ollama.  
- **Customizable Translation:**  
  - **Target Language:** Supports a wide range of languages.  
  - **Style Control:** Choose between "Natural," "Formal," or "Simple clear" translation styles.  
  - **Advanced Prompting:** Power users can provide a completely custom system prompt to fine-tune the translation process.  
- **Format Preservation:** Intelligently protects and restores SRT timecodes and basic HTML tags (like `<i>` or `<b>`) to ensure the translated file maintains correct formatting.  
- **User Profiles:** Save and load different configurations (model, language, style, prompt) as profiles for quick and easy setup.  
- **Theming:** Includes multiple UI themes (Light, Dark, Nord, Dracula, etc.) for a personalized look and feel.  
- **Resilience:** Includes retry logic for network requests to handle temporary connection issues with the Ollama server.  

## How It Works

1. The user selects a file or folder and sets the desired translation parameters (target language, style, Ollama model).  
2. The application reads each `.srt` file, parsing it into individual subtitle blocks (index, timecode, text).  
3. For each block of text, it temporarily replaces timecodes and HTML tags with unique placeholders (e.g., `<TIME_0>`, `<BTAG_1>`).  
4. It constructs a system prompt instructing the LLM to translate the text while keeping the placeholders unchanged.  
5. The text is sent to the local Ollama API for translation.  
6. Upon receiving the translated text, the application restores the original timecodes and HTML tags from the placeholders.  
7. A new `.srt` file is created with the translated content, named with the corresponding language code (e.g., `my_movie.en.srt` becomes `my_movie.sv.srt`).  

## Dependencies

To run this application, you need the following:

- **Ollama:** You must have Ollama installed and running on your system. You also need to have at least one language model downloaded (e.g., `ollama pull llama3`).  
- **Python 3:** The script is written for Python 3.  
- **Python Libraries:** You can install the required Python libraries using pip:  
  ```bash
  pip install PyQt6 requests

import os
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("install_finbert")

def install_finbert():
    logger.info("Starting local installation of FinBERT...")
    
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
    except ImportError:
        logger.error("The 'transformers' and 'torch' libraries are required.")
        logger.error("Please run: pip install transformers torch")
        return False
        
    model_name = "ProsusAI/finbert"
    save_directory = Path("data/finbert")
    
    if save_directory.exists() and any(save_directory.iterdir()):
        logger.info(f"FinBERT is already installed at {save_directory.absolute()}")
        return True
        
    save_directory.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Downloading tokenizer for {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.save_pretrained(str(save_directory))
    
    logger.info(f"Downloading model for {model_name}... (This may take a while)")
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.save_pretrained(str(save_directory))
    
    logger.info(f"FinBERT successfully downloaded and saved to {save_directory.absolute()}")
    return True

if __name__ == "__main__":
    install_finbert()

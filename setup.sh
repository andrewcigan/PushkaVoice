#!/bin/bash
set -e

echo "=== GigaAM Dictation App Setup ==="

# Check conda
if ! command -v conda &> /dev/null; then
    echo "ERROR: conda not found. Install Miniconda first."
    exit 1
fi

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
fi

# Create conda environment
echo "Creating conda environment 'dictation' with Python 3.11..."
conda create -n dictation python=3.11 -y

echo "Activating environment..."
eval "$(conda shell.bash hook)"
conda activate dictation

# Install GigaAM
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GIGAAM_DIR="$(dirname "$SCRIPT_DIR")/GigaAM"

if [ ! -d "$GIGAAM_DIR" ]; then
    echo "Cloning GigaAM..."
    git clone https://github.com/salute-developers/GigaAM.git "$GIGAAM_DIR"
fi

cd "$GIGAAM_DIR"
echo "Installing GigaAM..."
pip install -e .
echo "Installing GigaAM longform support..."
pip install -e ".[longform]"

# Install app dependencies
echo "Installing app dependencies..."
pip install rumps pynput sounddevice python-dotenv pyobjc-framework-Cocoa

# Check .env
cd "$SCRIPT_DIR"
if [ ! -f .env ]; then
    echo ""
    echo "IMPORTANT: Create .env file with your HuggingFace token:"
    echo "  echo 'HF_TOKEN=hf_your_token' > $SCRIPT_DIR/.env"
    echo ""
    echo "Get token at: https://huggingface.co/settings/tokens"
    echo "Accept pyannote terms at: https://huggingface.co/pyannote/segmentation-3.0"
fi

echo ""
echo "=== Setup complete! ==="
echo "To run: conda activate dictation && cd $SCRIPT_DIR && python app.py"

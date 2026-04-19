# OCR Overlay

A desktop overlay application for real-time text extraction and translation from selected screen regions.


## Overview

OCR Overlay enables users to define regions on the screen, perform continuous OCR, and render translated text directly within those regions. The application is designed for minimal UI interference and efficient interaction.

<img width="1680" height="1050" alt="image" src="https://github.com/user-attachments/assets/6da8acc1-1e8e-4c24-91f0-8ad6ad504f7f" />

https://github.com/user-attachments/assets/8a09986a-0450-4e85-bf87-6db52dc0288c


## Features

- Region-based screen OCR  
- Real-time text recognition and translation  
- Editable overlay regions (move and resize)  
- Customizable background styling  
- Global hotkey toggle (`Ctrl + 1`)  
- Lightweight, non-intrusive overlay  


## Requirements

- Python 3.10  
- Windows  
- Internet connection (initial setup only)  


## Usage

1. Extract the release package  
2. Run: `run.bat`
3. Initial setup takes time since requirements are being downloaded
4. Press `Ctrl + 1` to toggle edit mode
5. Create and adjust (move / resize) regions to translate as required


## Tweakable Parameters

| Setting           | Description                              |
|------------------|------------------------------------------|
| OCR Interval     | Time between OCR updates (ms)             |
| Stability Frames | Frames required before updating text      |
| Diff Threshold   | Sensitivity to text changes              |
| OCR Confidence   | Minimum confidence threshold              |
| X Offset        | Horizontal adjustment of text position    |
| Y Offset        | Vertical adjustment of text position      |
| Background Color| Set overlay background color              |


## Controls

| Action         | Input          |
|----------------|----------------|
| Toggle mode    | `Ctrl + 1`    |
| Create region  | Click + drag   |
| Move region    | Drag inside    |
| Resize region  | Drag bottom-right edge     |


### Runtime Metrics

| Metric    | Description                     |
|-----------|---------------------------------|
| CPU       | Current CPU usage               |
| OCR/sec   | OCR processing rate             |


## Tech Stack

- PyQt5  
- PaddleOCR  
- Deep Translator  
- OpenCV / dxcam  


## Note

- Performance drops according to parameters set
- Currently supports translation from Chinese only.
- Additional language support will be added soon.

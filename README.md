# SafePath

**SafePath** is a navigation platform that helps users compare safer and shorter routes through urban areas. It uses bundled incident records and deterministic road-segment risk scoring, without requiring an external AI service.

## Technical Architecture

- **Frontend**: Django templates, custom CSS, and Leaflet.js with OpenStreetMap tiles
- **Backend**: Django with Django REST Framework
- **Database**: SQLite for Django data, plus a bundled CSV incident dataset

## How It Works

- **Collect Data**: Load the bundled crime dataset and normalise its coordinates and severity.
- **Process Geo-Data**: Measure incident proximity to road segments.
- **Compute Safety Index**: Apply deterministic severity and proximity scoring.
- **Generate Routes**: Use graph search algorithms to prioritise safety or distance.
- **Visualize**: Route overlays displayed using Leaflet.js.

## Installation & Setup
1. Clone the repository 
```
git clone https://github.com/LilSuperUser/SafePath.git
cd ./SafePath
```

2. Install the dependencies in a python virtual environment 
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Configure the application
```
cp .env.example .env
```
Replace `DJANGO_SECRET_KEY` with a random value. Set `DJANGO_DEBUG=False` in production.

4. Start the server
```
python manage.py runserver
```

5. Visit 127.0.0.1:8000 <br>


## License

This project is licensed under the GPL v3 License. You are free to use, modify, and distribute this software under the terms of the [GPL v3 license](./LICENSE)

from fastapi import APIRouter
import requests

router = APIRouter(prefix="/recipes", tags=["recipes"])

API_KEY = "d0cd5334fea44828b7525009b40b0e0a"

@router.get("")
def get_recipes():
    try:
        ingredients = ["milk", "eggs", "bread"]

        url = "https://api.spoonacular.com/recipes/findByIngredients"

        params = {
            "ingredients": ",".join(ingredients),
            "number": 5,
            "apiKey": API_KEY
        }

        response = requests.get(url, params=params, timeout=5)

        return response.json()

    except Exception as e:
        return {"error": str(e)}
from fastapi import APIRouter, Depends
import requests
import aiosqlite
from core.database import db_dependency

router = APIRouter(prefix="/recipes", tags=["recipes"])

API_KEY = "d0cd5334fea44828b7525009b40b0e0a"

@router.get("")
async def get_recipes(db: aiosqlite.Connection = Depends(db_dependency)):
    try:
        cur = await db.execute("SELECT name FROM items")
        rows = await cur.fetchall()
        
        # dynamic array of ingredient tags to search by
        ingredients = [row[0] for row in rows] if rows else ["milk", "eggs", "bread"]
        
        # limit ingredients to top 5 to avoid overly specific queries which yield 0 recipes
        ingredients = ingredients[:5]

        url = "https://api.spoonacular.com/recipes/findByIngredients"

        params = {
            "ingredients": ",".join(ingredients),
            "number": 5,
            "apiKey": API_KEY,
            "ranking": 2 # 1 = maximize used ingredients, 2 = minimize missing ingredients
        }

        response = requests.get(url, params=params, timeout=5)

        return response.json()

    except Exception as e:
        return {"error": str(e)}
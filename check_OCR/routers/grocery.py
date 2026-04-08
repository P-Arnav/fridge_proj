from fastapi import APIRouter

router = APIRouter(prefix="/grocery", tags=["grocery"])

grocery_list = []

@router.post("/add")
def add_item(name: str, quantity: int):
    item = {
        "name": name,
        "quantity": quantity,
        "status": "pending"
    }
    grocery_list.append(item)
    return item

@router.get("")
def get_items():
    return grocery_list

@router.put("/buy/{index}")
def mark_bought(index: int):
    grocery_list[index]["status"] = "bought"
    return grocery_list[index]
import unittest

from common.testutil import bearer, load_service, temp_db_url

svc = load_service("menu")
ADMIN, STUDENT = bearer(9, "boss", "admin"), bearer(1, "alice", "student")
NEW_ITEM = {"name": "Tea", "description": "Hot masala chai.", "price": 1500, "category_id": 5, "available": True}


class MenuServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = svc.create_app(temp_db_url()).test_client()

    def test_seeded_menu_is_public(self):
        items = self.client.get("/api/menu").json["items"]
        self.assertEqual(len(items), 6)
        self.assertEqual(len(self.client.get("/api/menu/categories").json["categories"]), 6)

    def test_search_and_category_filter(self):
        self.assertEqual([i["name"] for i in self.client.get("/api/menu?search=burg").json["items"]], ["Classic Burger"])
        self.assertEqual(len(self.client.get("/api/menu?category=5").json["items"]), 1)

    def test_admin_endpoints_are_protected(self):
        self.assertEqual(self.client.post("/api/menu/items", json=NEW_ITEM).status_code, 401)
        self.assertEqual(self.client.post("/api/menu/items", json=NEW_ITEM, headers=STUDENT).status_code, 403)

    def test_admin_crud_and_availability(self):
        created = self.client.post("/api/menu/items", json=NEW_ITEM, headers=ADMIN)
        self.assertEqual(created.status_code, 201)
        fid = created.json["item"]["id"]
        upd = self.client.put(f"/api/menu/items/{fid}", json={**NEW_ITEM, "price": 1800}, headers=ADMIN)
        self.assertEqual(upd.json["item"]["price"], 1800)
        self.client.post(f"/api/menu/items/{fid}/toggle", headers=ADMIN)
        names = [i["name"] for i in self.client.get("/api/menu").json["items"]]
        self.assertNotIn("Tea", names)                       # hidden from students
        all_names = [i["name"] for i in self.client.get("/api/menu/admin/items", headers=ADMIN).json["items"]]
        self.assertIn("Tea", all_names)                      # still visible to admin
        self.assertEqual(self.client.delete(f"/api/menu/items/{fid}", headers=ADMIN).status_code, 200)
        self.assertEqual(self.client.get(f"/api/menu/items/{fid}").status_code, 404)

    def test_validation(self):
        for bad in ({**NEW_ITEM, "price": -1}, {**NEW_ITEM, "price": "12"}, {**NEW_ITEM, "name": ""},
                    {**NEW_ITEM, "category_id": 99}, {**NEW_ITEM, "category_id": [1]}):
            self.assertEqual(self.client.post("/api/menu/items", json=bad, headers=ADMIN).status_code, 400, bad)

    def test_lookup_returns_current_prices_even_if_unavailable(self):
        self.client.post("/api/menu/items/1/toggle", headers=ADMIN)
        items = {i["id"]: i for i in self.client.post("/api/menu/lookup", json={"ids": [1, 2, 999]}).json["items"]}
        self.assertEqual(set(items), {1, 2})
        self.assertEqual(items[1]["available"], 0)
        self.assertEqual(self.client.post("/api/menu/lookup", json={"ids": ["x"]}).status_code, 400)


if __name__ == "__main__":
    unittest.main()

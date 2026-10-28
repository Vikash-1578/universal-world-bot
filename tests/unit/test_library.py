"""Milestone 5: library, images, QC, versions, casting, packages. Images are generated with Pillow in the test."""
import io
import json
import zipfile

from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image, ImageDraw

from app.characters import imaging, packages, templates
from app.core.errors import Conflict, InvalidInput
from app.models.imagegen import ComfyUI, ImageGenUnavailable
from tests.helpers import TempDirCase, make_hub


def figure_on_green(w=400, h=700, bg=(0, 200, 0)) -> bytes:
    """A simple stick-ish figure (head, neck, body, two legs) on a green screen."""
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((140, 40, 260, 160), fill=(240, 200, 160))      # head
    d.rectangle((185, 160, 215, 190), fill=(240, 200, 160))   # neck (narrow)
    d.rectangle((120, 190, 280, 470), fill=(30, 60, 200))     # body
    d.rectangle((130, 470, 185, 680), fill=(40, 40, 40))      # left leg
    d.rectangle((215, 470, 270, 680), fill=(40, 40, 40))      # right leg
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def busy_photo() -> bytes:
    im = Image.linear_gradient("L").convert("RGB").resize((500, 500))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def background(w=1600, h=900) -> bytes:
    im = Image.new("RGB", (w, h), (120, 180, 240))
    ImageDraw.Draw(im).rectangle((0, h // 2, w, h), fill=(60, 160, 60))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


class ImagingTests(TempDirCase):
    async def test_cutout_and_rig_qc(self):
        im = imaging.open_image(figure_on_green())
        cut = imaging.cutout(im)
        self.assertIsNotNone(cut)
        self.assertEqual(cut.mode, "RGBA")
        self.assertLess(cut.width, 200)  # cropped to the figure
        qc = imaging.analyse(cut)
        self.assertTrue(qc.ok, qc.problems)
        self.assertTrue(qc.transparent and qc.legs)
        self.assertIsNotNone(qc.neck_row)
        self.assertIsNone(imaging.cutout(imaging.open_image(busy_photo())))  # no plain border -> not cut
        bad = imaging.analyse(imaging.open_image(busy_photo()))
        self.assertFalse(bad.ok)
        self.assertIn("Background nahi hata", bad.text())
        with self.assertRaises(InvalidInput):
            imaging.open_image(b"not an image")


class LibraryTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.lib = self.hub.library

    async def asyncTearDown(self):
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_templates_catalog(self):
        self.assertGreaterEqual(len(templates.entries()), 1100)
        self.assertGreaterEqual(len(templates.entries(kind="place")), 90)
        self.assertEqual(templates.search("sher", "actor")[0]["kind"], "actor")
        self.assertEqual(templates.search("jungle", "place")[0]["kind"], "place")
        self.assertTrue(templates.categories("actor"))

    async def test_create_versions_images_qc(self):
        it = self.lib.create_item("character", "Golu Khargosh", {"description": "chhota safed khargosh", "hacker": "x"})
        self.assertEqual((it["id"], it["version"], it["profile"]), ("golu-khargosh", 1, {"description": "chhota safed khargosh"}))
        self.assertEqual(self.lib.create_item("character", "Golu Khargosh")["id"], "golu-khargosh-2")
        it2, qc = self.lib.add_image(it["id"], "main", figure_on_green())
        self.assertEqual((it2["version"], it2["qc_status"]), (2, "ok"))
        self.assertTrue(qc.ok)
        main = self.lib.file_path(it2, "main")
        self.assertTrue(main.exists() and Image.open(main).mode == "RGBA")
        it3, _ = self.lib.add_image(it["id"], "expr:happy", figure_on_green(bg=(255, 255, 255)))
        self.assertIn("expr:happy", it3["files"])
        self.assertEqual(self.lib.get(it["id"], 2)["files"].keys(), it2["files"].keys())  # old version untouched
        it4, qc = self.lib.add_image(it["id"], "main", busy_photo())
        self.assertEqual(it4["qc_status"], "needs_fix")
        with self.assertRaises(InvalidInput):
            self.lib.add_image(it["id"], "background", background())
        protected = self.hub.db.one("SELECT COUNT(*) AS n FROM assets WHERE protected = 1 AND asset_type LIKE 'library:%'")["n"]
        self.assertGreaterEqual(protected, 6)
        env = self.lib.from_template("pl_jungle" if templates.get("pl_jungle") else templates.entries(kind="place")[0]["id"])
        self.assertEqual(env["kind"], "environment")
        env2, qc = self.lib.add_image(env["id"], "background", background())
        self.assertEqual((env2["files"]["background"]["w"], env2["files"]["background"]["h"]), (1920, 1080))
        self.assertTrue(qc.ok)
        with self.assertRaises(Conflict):
            self.lib.approve_qc(self.lib.create_item("prop", "Chhatri")["id"])

    async def test_casting_pins_versions(self):
        pid = self.hub.projects.create_project("Race", "2d")["id"]
        it = self.lib.create_item("character", "Sheru")
        self.lib.cast(pid, "Sher", it["id"])
        self.lib.update_profile(it["id"], {"description": "naya look"})
        c = self.lib.casting(pid)["Sher"]
        self.assertEqual((c["version"], c["outdated"]), (1, True))  # project still on v1
        self.lib.cast(pid, "Sher", it["id"])
        self.assertFalse(self.lib.casting(pid)["Sher"]["outdated"])
        self.assertEqual(self.lib.used_by(it["id"])[0]["role"], "Sher")
        with self.assertRaises(Exception):  # library item used by a project cannot be deleted silently
            self.hub.db.execute("DELETE FROM library_items WHERE id = ?", (it["id"],))

    async def test_package_roundtrip_and_attacks(self):
        it = self.lib.create_item("character", "Pinky", {"description": "girl"})
        self.lib.add_image(it["id"], "main", figure_on_green())
        name, data = packages.export_item(self.lib, it["id"])
        self.assertTrue(name.endswith(".uwpkg.zip"))
        new = packages.import_package(self.lib, data)
        self.assertNotEqual(new["id"], it["id"])
        self.assertEqual(new["profile"]["description"], "girl")
        self.assertIn("main", new["files"])
        # tampered file -> rejected, nothing created
        before = self.hub.db.one("SELECT COUNT(*) AS n FROM library_items")["n"]
        z = zipfile.ZipFile(io.BytesIO(data))
        m = json.loads(z.read("manifest.json"))
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as out:
            out.writestr("manifest.json", json.dumps(m))
            for f in m["files"].values():
                out.writestr(f["file"], b"\x89PNGtampered")
        with self.assertRaises(InvalidInput):
            packages.import_package(self.lib, bad.getvalue())
        slip = io.BytesIO()
        with zipfile.ZipFile(slip, "w") as out:
            out.writestr("../../evil.png", b"x")
            out.writestr("manifest.json", "{}")
        with self.assertRaises(InvalidInput):
            packages.import_package(self.lib, slip.getvalue())
        with self.assertRaises(InvalidInput):
            packages.import_package(self.lib, b"not a zip")
        self.assertEqual(self.hub.db.one("SELECT COUNT(*) AS n FROM library_items")["n"], before)


class ComfyTests(TempDirCase):
    """ComfyUI is replaced by a fake HTTP server here (test double) — this proves our protocol handling only."""

    async def test_generate_flow_and_unavailable(self):
        png = figure_on_green()
        seen = {}

        async def info(req):
            return web.json_response({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["cartoonXL.safetensors"]]}}}})

        async def prompt(req):
            seen["graph"] = (await req.json())["prompt"]
            return web.json_response({"prompt_id": "p1"})

        async def history(req):
            return web.json_response({"p1": {"outputs": {"7": {"images": [{"filename": "uwb_1.png", "subfolder": "", "type": "output"}]}}}})

        async def view(req):
            return web.Response(body=png, content_type="image/png")

        app = web.Application()
        app.router.add_get("/object_info/CheckpointLoaderSimple", info)
        app.router.add_post("/prompt", prompt)
        app.router.add_get("/history/p1", history)
        app.router.add_get("/view", view)
        srv = TestServer(app)
        await srv.start_server()
        try:
            c = ComfyUI(f"http://{srv.host}:{srv.port}")
            self.assertTrue(await c.available())
            data = await c.generate("cute rabbit", width=512, height=768, seed=7)
            self.assertEqual(data, png)
            self.assertEqual(seen["graph"]["1"]["inputs"]["ckpt_name"], "cartoonXL.safetensors")
            self.assertEqual(seen["graph"]["5"]["inputs"]["seed"], 7)
        finally:
            await srv.close()
        with self.assertRaises(ImageGenUnavailable):
            await ComfyUI("http://127.0.0.1:9").generate("x")


class CloudImageTests(TempDirCase):
    """Cloudflare + ComfyUI replaced by fake HTTP servers (test doubles): proves routing + opt-in gate only."""

    async def test_router_cloud_gate_and_order(self):
        import base64

        from app.models.imagegen import CloudflareImages, ComfyUI, ImageRouter

        png = figure_on_green()
        calls = []

        async def run(req):
            calls.append(req.match_info["m"])
            j = await req.json()
            if "flux" in req.match_info["m"] and "seed" in j:
                return web.json_response({"errors": [{"code": 5006}]}, status=400)
            return web.json_response({"result": {"image": base64.b64encode(png).decode()}})

        app = web.Application()
        app.router.add_post("/cf/{acc}/ai/run/{m:.*}", run)
        srv = TestServer(app)
        await srv.start_server()
        try:
            cloud_on = {"v": False}
            cf = CloudflareImages("acc", "tok", base=f"http://{srv.host}:{srv.port}/cf")
            r = ImageRouter(ComfyUI("http://127.0.0.1:9"), cf, lambda: cloud_on["v"])
            self.assertFalse(await r.available())  # cloud OFF + no ComfyUI -> nothing, no network call to cloud
            with self.assertRaises(ImageGenUnavailable):
                await r.generate("x")
            self.assertEqual(calls, [])
            cloud_on["v"] = True
            self.assertEqual(await r.sources(), {"comfyui": False, "cloudflare": True})
            self.assertEqual(await r.generate("rabbit", seed=3), png)
            self.assertEqual(r.last_provider, "cloudflare")
            self.assertEqual(len(calls), 2)  # with seed -> 400, retried without seed
            self.assertIsNone(ImageRouter(ComfyUI(), CloudflareImages("", ""), lambda: True).cloud)
        finally:
            await srv.close()


class GroundAndLanguageTests(TempDirCase):
    async def test_grass_disc_removed_and_hindi_names_redescribed(self):
        from app.characters.jobs import is_english

        im = Image.new("RGB", (400, 760), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.ellipse((60, 660, 340, 740), fill=(70, 160, 60), outline=(30, 80, 30), width=4)  # AI-style grass disc
        d.ellipse((140, 40, 260, 160), fill=(240, 200, 160))
        d.rectangle((185, 160, 215, 190), fill=(240, 200, 160))
        d.rectangle((120, 190, 280, 470), fill=(200, 60, 60))
        d.rectangle((130, 470, 185, 690), fill=(40, 40, 120))
        d.rectangle((215, 470, 270, 690), fill=(40, 40, 120))
        cut = imaging.cutout(im)
        self.assertGreater(cut.width, 250)  # disc is part of the cut-out
        clean = imaging.remove_ground(cut)
        self.assertLess(clean.width, 180)  # only the figure is left
        green = [p for p in clean.getdata() if p[3] > 100 and p[1] > p[0] + 18 and p[1] > p[2] + 8]
        self.assertEqual(green, [])  # no visible grass left
        self.assertFalse(is_english("लोमड़ी"))
        self.assertTrue(is_english("A cute orange cartoon fox"))

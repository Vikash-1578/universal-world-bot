"""Character expression pack. ComfyUI is a FAKE HTTP server here (test double) that 'repaints' the transparent face
area with a flat colour — this proves our upload / masked-graph / compose / library / renderer wiring, not AI quality."""
import io

from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image, ImageChops

from app.characters import pack
from tests.helpers import TempDirCase, make_hub
from tests.integration.test_voice_lipsync import face_figure


class PackTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.graphs, self.uploads = [], {}

        async def info(req):
            return web.json_response({"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sdxl.safetensors"]]}}}})

        async def upload(req):
            data = await req.post()
            f = data["image"]
            self.uploads[f.filename] = f.file.read()
            return web.json_response({"name": f.filename, "subfolder": "", "type": "input"})

        async def prompt(req):
            g = (await req.json())["prompt"]
            self.graphs.append(g)
            return web.json_response({"prompt_id": f"p{len(self.graphs)}"})

        async def history(req):
            pid = req.match_info["pid"]
            return web.json_response({pid: {"outputs": {"7": {"images": [{"filename": pid + ".png", "subfolder": "", "type": "output"}]}}}})

        async def view(req):
            g = self.graphs[int(req.query["filename"][1:-4]) - 1]
            src = Image.open(io.BytesIO(self.uploads[g["4"]["inputs"]["image"]]))
            out = src.convert("RGB")
            hole = ImageChops.invert(src.getchannel("A"))
            out.paste((0, 160, 255), mask=hole)  # 'new face' = flat blue where the picture was transparent
            buf = io.BytesIO()
            out.save(buf, "PNG")
            return web.Response(body=buf.getvalue(), content_type="image/png")

        app = web.Application()
        app.router.add_get("/object_info/CheckpointLoaderSimple", info)
        app.router.add_post("/upload/image", upload)
        app.router.add_post("/prompt", prompt)
        app.router.add_get("/history/{pid}", history)
        app.router.add_get("/view", view)
        self.srv = TestServer(app)
        await self.srv.start_server()
        self.hub.imagegen.url = f"http://{self.srv.host}:{self.srv.port}"

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        await self.srv.close()
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_pack_repaints_only_the_face_and_renderer_uses_it(self):
        lib = self.hub.library
        it = lib.create_item("character", "Golu", {"look": "a cheerful boy in a red shirt"})
        lib.add_image(it["id"], "main", face_figure())
        pid = self.hub.projects.create_project("P", "2d")["id"]
        lib.cast(pid, "Golu", it["id"])
        self.hub.jobs.submit_job(pack.JOB, None, {"item_id": it["id"], "exprs": list(pack.ORDER),
                                                  "recast": {"project_id": pid, "role": "Golu"}}, 5)
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=60)
        cur = lib.get(it["id"])
        self.assertEqual({k for k in cur["files"] if k.startswith("expr:") and not k.endswith(":original")},
                         {f"expr:{e}" for e in pack.ORDER})
        self.assertEqual(lib.casting(pid)["Golu"]["version"], cur["version"])  # project moved to the pack version
        g = self.graphs[0]
        self.assertEqual(g["9"]["class_type"], "SetLatentNoiseMask")
        self.assertLess(g["5"]["inputs"]["denoise"], 1.0)  # starts from the original face -> same character
        self.assertIn("mouth open", self.graphs[0]["2"]["inputs"]["text"])  # first expression made = talk
        main = Image.open(lib.file_path(cur, "main")).convert("RGBA")
        happy = Image.open(lib.file_path(cur, "expr:happy")).convert("RGBA")
        self.assertEqual(main.size, happy.size)
        diff = ImageChops.difference(main.convert("RGB"), happy.convert("RGB")).getbbox()
        fx0, fy0, fx1, fy1 = pack.face_box(main)
        self.assertIsNotNone(diff)
        self.assertTrue(diff[1] >= fy0 - 3 and diff[3] <= fy1 + 3, (diff, (fx0, fy0, fx1, fy1)))  # only the face changed
        self.assertEqual(main.getchannel("A").tobytes(), happy.getchannel("A").tobytes())  # same outline / transparency
        # the 2D renderer picks the pack up: emotion faces + talk picture for the mouth
        from app.animation.two_d.rig import Rig

        variants = {e: Image.open(lib.file_path(cur, f"expr:{e}")) for e in pack.ORDER}
        rig = Rig(main, variants)
        self.assertIn("happy", rig.var)
        self.assertTrue(rig.has_mouth())

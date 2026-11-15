"""Registro de rutas inventado con la forma del Supervisor (spec 011, T038).

No es código del Supervisor ni se importa nunca: el extractor lo lee con
`ast` y sigue las ramas de la API V1.
"""

raise RuntimeError("el extractor no debe importar el código que lee")

from aiohttp import hdrs, web  # noqa: E402


class RestAPI:
    async def load(self):
        self._register_panel()
        for version in self.enabled_versions:
            app = self.versions[version]
            self._register_demo(app)

    def _register_advanced_logs(self, path, syslog_identifier, app):
        app.add_routes(
            [
                web.get(f"{path}/logs", self.logs),
                web.get(f"{path}/logs/boots/{{bootid}}", self.logs),
            ]
        )

    def _register_demo(self, app):
        app.add_routes(
            [
                web.get("/demo/info", self.info),
                web.post("/demo/{app}/options", self.options),
                web.delete("/demo/{slug}", self.borrar),
                web.get("/demo/api/{path:.+}", self.proxy),
            ]
        )
        if app is self.versions[AppVersion.V1]:
            app.add_routes([web.post("/demo/solo_v1", self.v1)])
        else:
            app.add_routes([web.post("/demo/solo_v2", self.v2)])
        self._register_advanced_logs("/demo", "demo", app=app)
        app.add_routes([web.route(hdrs.METH_ANY, "/demo/comodin/{x}", self.todo)])

    def _register_panel(self):
        return [StaticResourceConfig("/app", self.carpeta)]

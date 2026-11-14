"""Tests de la retención de los safety backups de Hermes (spec 005, US8).

La retención BORRA backups completos del Supervisor. Lo único que la hace
segura es identificar sin ambigüedad qué backups creó Hermes: por eso se
apoya en una anotación propia (`safety_backups.json`) y nunca en el nombre a
secas, porque cualquiera puede crear un backup llamado `hermes-safety-…`.
Estos tests fijan esa identificación, el fail-closed y los enganches con el
safety backup automático y con `sv_create_safety_backup`.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import hermes.safety_retention as sr
from hermes.ha import HAConnectionError

_AHORA = 1_794_644_400.0  # instante fijo de los tests (noviembre de 2026)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _nombre(epoch: float) -> str:
    return "hermes-safety-" + datetime.fromtimestamp(
        epoch, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(i: int) -> str:
    return f"{i:08x}"


def _backup(slug: str, name: str, epoch: float, **extra: Any) -> dict[str, Any]:
    datos = {"slug": slug, "name": name, "date": _iso(epoch), "type": "full",
             "protected": False, "location": None, "locations": [None]}
    datos.update(extra)
    return datos


def _404() -> HAConnectionError:
    return HAConnectionError("Job does not exist", status=404)


class _Supervisor:
    """Supervisor simulado: `/backups`, `/jobs/{id}` y `DELETE /backups/{slug}`.

    Graba cada petición para poder afirmar cuántos `DELETE` hubo y en qué
    orden. `listado` puede ser una lista, otra cosa (forma rara) o una
    excepción.
    """

    def __init__(self, backups: Any = None, jobs: dict[str, Any] | None = None,
                 fallar_delete: set[str] | None = None,
                 post: dict[str, Any] | None = None) -> None:
        self.backups = backups if backups is not None else []
        self.jobs = jobs or {}
        self.fallar_delete = fallar_delete or set()
        self.post = post
        self.peticiones: list[tuple[str, str]] = []

    async def sv_request(self, method, path, json_body=None, params=None,
                         timeout_seconds=60.0):
        self.peticiones.append((method, path))
        if method == "GET" and path == "/backups":
            if isinstance(self.backups, Exception):
                raise self.backups
            if isinstance(self.backups, list):
                return {"backups": self.backups}
            return self.backups
        if method == "GET" and path.startswith("/jobs/"):
            job = self.jobs.get(path.rsplit("/", 1)[-1])
            if job is None:
                raise _404()
            if callable(job):
                job = job()
            if isinstance(job, Exception):
                raise job
            return job
        if method == "DELETE" and path.startswith("/backups/"):
            slug = path.rsplit("/", 1)[-1]
            if slug in self.fallar_delete:
                raise HAConnectionError("delete failed", status=500)
            self.backups = [b for b in self.backups if b.get("slug") != slug]
            return {}
        if method == "POST":
            return self.post
        raise AssertionError(f"petición inesperada {method} {path}")

    @property
    def deletes(self) -> list[str]:
        return [p.rsplit("/", 1)[-1] for m, p in self.peticiones if m == "DELETE"]


class _ConAnotacion(unittest.IsolatedAsyncioTestCase):
    """Base: anotación en un directorio temporal y reloj fijo."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "safety_backups.json"
        self._p = patch.object(sr, "LEDGER_PATH", self.ruta)
        self._p.start()
        self._t = patch("hermes.safety_retention.time.time", return_value=_AHORA)
        self._t.start()

    def tearDown(self) -> None:
        self._t.stop()
        self._p.stop()
        self._tmp.cleanup()

    def _entradas(self) -> list[dict[str, Any]]:
        return json.loads(self.ruta.read_text(encoding="utf-8"))["entries"]

    def _anotar(self, entradas: list[dict[str, Any]]) -> None:
        self.ruta.write_text(json.dumps({"version": 1, "entries": entradas}),
                             encoding="utf-8")

    @staticmethod
    def _confirmada(slug: str, name: str, launched: float,
                    origin: str = "auto") -> dict[str, Any]:
        return {"name": name, "job_id": None, "launched_at": launched,
                "origin": origin, "slug": slug, "confirmed_by": "job_reference"}

    def _cinco(self) -> tuple[list[dict], list[dict]]:
        """Cinco safety backups confirmados, uno por hora, el 0 el más antiguo."""
        entradas, backups = [], []
        for i in range(5):
            t = _AHORA - (5 - i) * 3600
            entradas.append(self._confirmada(_slug(i), _nombre(t), t))
            backups.append(_backup(_slug(i), _nombre(t), t + 30))
        return entradas, backups


# ── T048: la anotación ────────────────────────────────────────────────────────


class TestAnotacion(_ConAnotacion):
    async def test_record_launch_adds_unconfirmed_entry(self) -> None:
        await sr.record_launch("hermes-safety-20261114T083000Z", "abc123", origin="auto")
        [e] = self._entradas()
        self.assertEqual(e["name"], "hermes-safety-20261114T083000Z")
        self.assertEqual(e["job_id"], "abc123")
        self.assertEqual(e["origin"], "auto")
        self.assertIsNone(e["slug"])
        self.assertIsNone(e["confirmed_by"])
        self.assertEqual(e["launched_at"], _AHORA)

    async def test_record_launch_with_sync_slug_is_confirmed(self) -> None:
        await sr.record_launch("hermes-safety-20261114-083000", None,
                               origin="tool", slug="deadbeef")
        [e] = self._entradas()
        self.assertEqual(e["slug"], "deadbeef")
        self.assertEqual(e["confirmed_by"], "sync_response")

    async def test_record_launch_rejects_invalid_slug(self) -> None:
        # Un slug con '/' no se puede usar en `DELETE /backups/{slug}`: no
        # confirma nada.
        await sr.record_launch("hermes-safety-x", None, origin="tool", slug="../x")
        [e] = self._entradas()
        self.assertIsNone(e["slug"])
        self.assertIsNone(e["confirmed_by"])

    async def test_confirm_from_job_only_on_clean_success(self) -> None:
        await sr.record_launch("n1", "job1", origin="auto")
        await sr.confirm_from_job("job1", {"done": False, "errors": [], "reference": "aaaa0001"})
        self.assertIsNone(self._entradas()[0]["slug"])
        await sr.confirm_from_job("job1", {"done": True, "errors": [], "reference": None})
        self.assertIsNone(self._entradas()[0]["slug"])
        await sr.confirm_from_job("job1", {"done": "true", "errors": [], "reference": "aaaa0001"})
        self.assertIsNone(self._entradas()[0]["slug"])
        await sr.confirm_from_job("job1", {"done": True, "errors": [], "reference": "aaaa0001"})
        [e] = self._entradas()
        self.assertEqual(e["slug"], "aaaa0001")
        self.assertEqual(e["confirmed_by"], "job_reference")

    async def test_confirm_from_job_with_errors_removes_entry(self) -> None:
        await sr.record_launch("n1", "job1", origin="auto")
        await sr.record_launch("n2", "job2", origin="auto")
        await sr.confirm_from_job("job1", {"done": True, "reference": "aaaa0001",
                                           "errors": [{"message": "no space"}]})
        self.assertEqual([e["name"] for e in self._entradas()], ["n2"])

    async def test_corrupt_ledger_reads_empty_and_is_not_overwritten_on_read(self) -> None:
        self.ruta.write_text("{esto no es json", encoding="utf-8")
        sv = _Supervisor([_backup(_slug(1), _nombre(_AHORA - 7200), _AHORA - 7200)])
        resumen = await sr.apply_retention(sv, 1)
        self.assertEqual(sv.deletes, [])
        self.assertEqual(self.ruta.read_text(encoding="utf-8"), "{esto no es json")
        self.assertEqual(resumen["deleted"], [])
        # El siguiente lanzamiento sí la rehace.
        await sr.record_launch("n1", "job1", origin="auto")
        self.assertEqual([e["name"] for e in self._entradas()], ["n1"])

    async def test_ledger_with_wrong_shape_reads_empty(self) -> None:
        self.ruta.write_text(json.dumps({"version": 1, "entries": "x"}), encoding="utf-8")
        sv = _Supervisor([])
        await sr.apply_retention(sv, 1)
        self.assertEqual(sv.peticiones, [])

    async def test_more_than_100_entries_drops_oldest_unconfirmed_first(self) -> None:
        entradas = []
        for i in range(100):
            e = self._confirmada(_slug(i), f"n{i}", _AHORA - 10_000 + i)
            if i % 2 == 0:
                e["slug"] = None
                e["confirmed_by"] = None
            entradas.append(e)
        self._anotar(entradas)
        await sr.record_launch("nuevo", "jobn", origin="auto")
        nombres = [e["name"] for e in self._entradas()]
        self.assertEqual(len(nombres), 100)
        # La más antigua no confirmada (n0) sale; la confirmada n1, no.
        self.assertNotIn("n0", nombres)
        self.assertIn("n1", nombres)
        self.assertIn("nuevo", nombres)

    async def test_write_is_atomic(self) -> None:
        reemplazos: list[tuple[str, str]] = []
        original = Path.replace

        def _espia(self_path: Path, destino: Any) -> Any:
            reemplazos.append((self_path.name, Path(destino).name))
            return original(self_path, destino)

        with patch.object(Path, "replace", _espia):
            await sr.record_launch("n1", "job1", origin="auto")
        self.assertEqual(reemplazos, [("safety_backups.json.tmp", "safety_backups.json")])
        self.assertFalse(self.ruta.with_name("safety_backups.json.tmp").exists())


# ── T049: apply_retention ─────────────────────────────────────────────────────


class TestApplyRetention(_ConAnotacion):
    async def test_a_keeps_newest_and_deletes_oldest_first(self) -> None:
        entradas, backups = self._cinco()
        self._anotar(entradas)
        sv = _Supervisor(backups)
        resumen = await sr.apply_retention(sv, 3)
        self.assertEqual(sv.deletes, [_slug(0), _slug(1)])
        self.assertEqual(sorted(e["slug"] for e in self._entradas()),
                         [_slug(2), _slug(3), _slug(4)])
        self.assertEqual(resumen["deleted"], [entradas[0]["name"], entradas[1]["name"]])

    async def test_b_user_backup_with_hermes_name_never_counts(self) -> None:
        entradas, backups = self._cinco()
        self._anotar(entradas[2:])  # tres anotados
        # Un backup del usuario con nombre de Hermes, sin anotar.
        backups.append(_backup("cafe0001", "hermes-safety-20261101T000000Z",
                               _AHORA - 30 * 86400))
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertEqual(sv.deletes, [])

    async def test_c_manual_name_never_deleted_even_if_annotated(self) -> None:
        entradas, backups = self._cinco()
        entradas[0]["name"] = "hermes-safety-manual"
        backups[0]["name"] = "hermes-safety-manual"
        self._anotar(entradas)
        sv = _Supervisor(backups)
        resumen = await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)
        self.assertEqual(sv.deletes, [_slug(1)])
        self.assertIn("hermes-safety-manual", json.dumps(resumen["excluded"]))

    async def test_d_slug_with_other_name_is_excluded_with_reason(self) -> None:
        entradas, backups = self._cinco()
        backups[0]["name"] = "my-own-backup"
        self._anotar(entradas)
        sv = _Supervisor(backups)
        resumen = await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)
        motivos = {x["name"]: x["reason"] for x in resumen["excluded"]}
        self.assertEqual(motivos[entradas[0]["name"]], "name_mismatch")

    async def _excluido(self, **cambio: Any) -> None:
        entradas, backups = self._cinco()
        backups[0].update(cambio)
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)
        self.assertEqual(sv.deletes, [_slug(1)])

    async def test_e_protected_is_excluded(self) -> None:
        await self._excluido(protected=True)

    async def test_f_two_locations_is_excluded(self) -> None:
        await self._excluido(locations=[None, "nas"])

    async def test_f_location_list_without_locations_is_excluded(self) -> None:
        backup = {"location": [None, "nas"]}
        entradas, backups = self._cinco()
        del backups[0]["locations"]
        backups[0].update(backup)
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)

    async def test_g_partial_is_excluded(self) -> None:
        await self._excluido(type="partial")

    async def test_h_unreadable_date_is_excluded(self) -> None:
        await self._excluido(date="ayer por la tarde")

    async def test_h_naive_date_is_excluded(self) -> None:
        await self._excluido(date="2026-11-14T08:00:00")

    async def test_i_listing_fails_no_delete(self) -> None:
        entradas, _ = self._cinco()
        self._anotar(entradas)
        for listado in (HAConnectionError("boom", status=500), {"backups": "x"},
                        ["no-dict"], {"otra": []}):
            sv = _Supervisor(listado)
            resumen = await sr.apply_retention(sv, 1)
            self.assertEqual(sv.deletes, [], listado)
            self.assertEqual(resumen["deleted"], [])
        # Y la anotación no se ha tocado: un listado roto no es «ya no existe».
        self.assertEqual(len(self._entradas()), 5)

    async def test_j_first_delete_failure_stops(self) -> None:
        entradas, backups = self._cinco()
        self._anotar(entradas)
        sv = _Supervisor(backups, fallar_delete={_slug(0)})
        resumen = await sr.apply_retention(sv, 1)
        self.assertEqual(sv.deletes, [_slug(0)])
        self.assertEqual(resumen["deleted"], [])
        self.assertEqual(len(self._entradas()), 5)

    async def test_k_at_most_five_deletes_per_run(self) -> None:
        entradas, backups = [], []
        for i in range(13):
            t = _AHORA - (13 - i) * 3600
            entradas.append(self._confirmada(_slug(i), _nombre(t), t))
            backups.append(_backup(_slug(i), _nombre(t), t + 30))
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 1)
        self.assertEqual(sv.deletes, [_slug(i) for i in range(5)])

    async def test_l_keep_zero_makes_no_request(self) -> None:
        entradas, backups = self._cinco()
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 0)
        self.assertEqual(sv.peticiones, [])

    async def test_candidates_not_above_keep_delete_nothing(self) -> None:
        entradas, backups = self._cinco()
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 5)
        self.assertEqual(sv.deletes, [])

    async def test_m_unique_name_and_close_date_confirms(self) -> None:
        entradas, backups = self._cinco()
        # La más antigua no tiene slug ni job consultable.
        entradas[0].update(slug=None, confirmed_by=None, job_id=None)
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertEqual(sv.deletes, [_slug(0), _slug(1)])

    async def test_m_two_backups_with_same_name_do_not_confirm(self) -> None:
        entradas, backups = self._cinco()
        entradas[0].update(slug=None, confirmed_by=None, job_id=None)
        backups.append(_backup("cafe0002", backups[0]["name"], entradas[0]["launched_at"]))
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)
        self.assertNotIn("cafe0002", sv.deletes)
        self.assertEqual(sv.deletes, [_slug(1)])
        self.assertIsNone(self._entradas()[0]["slug"])

    async def test_m_date_far_from_launch_does_not_confirm(self) -> None:
        entradas, backups = self._cinco()
        entradas[0].update(slug=None, confirmed_by=None, job_id=None)
        backups[0]["date"] = _iso(entradas[0]["launched_at"] + 11 * 60)
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)

    async def test_job_reference_confirms_unconfirmed_entry(self) -> None:
        entradas, backups = self._cinco()
        entradas[0].update(slug=None, confirmed_by=None, job_id="job0")
        # Mismo nombre en dos backups: solo la referencia del job desambigua.
        backups.append(_backup("cafe0003", backups[0]["name"], entradas[0]["launched_at"]))
        self._anotar(entradas)
        sv = _Supervisor(backups, jobs={"job0": {"done": True, "errors": [],
                                                 "reference": _slug(0)}})
        await sr.apply_retention(sv, 3)
        self.assertEqual(sv.deletes, [_slug(0), _slug(1)])
        self.assertNotIn("cafe0003", sv.deletes)

    async def test_failed_job_drops_entry_without_deleting(self) -> None:
        entradas, backups = self._cinco()
        entradas[0].update(slug=None, confirmed_by=None, job_id="job0")
        self._anotar(entradas)
        sv = _Supervisor(backups, jobs={"job0": {"done": True, "reference": _slug(0),
                                                 "errors": [{"message": "x"}]}})
        await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)
        self.assertNotIn(entradas[0]["name"], [e["name"] for e in self._entradas()])

    async def test_n_unconfirmed_older_than_7_days_leaves_ledger(self) -> None:
        viejo = _AHORA - 8 * 86400
        entradas, backups = self._cinco()
        entradas.insert(0, {"name": _nombre(viejo), "job_id": None, "launched_at": viejo,
                            "origin": "auto", "slug": None, "confirmed_by": None})
        # Su backup existe pero con fecha incoherente: no se puede confirmar.
        backups.append(_backup("cafe0004", _nombre(viejo), viejo + 3600))
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertNotIn("cafe0004", sv.deletes)
        self.assertNotIn(_nombre(viejo), [e["name"] for e in self._entradas()])

    async def test_confirmed_entry_whose_backup_is_gone_leaves_ledger(self) -> None:
        entradas, backups = self._cinco()
        self._anotar(entradas)
        sv = _Supervisor(backups[1:])
        await sr.apply_retention(sv, 4)
        self.assertEqual(sv.deletes, [])
        self.assertNotIn(_slug(0), [e["slug"] for e in self._entradas()])

    async def test_duplicated_slug_in_listing_is_excluded(self) -> None:
        entradas, backups = self._cinco()
        backups.append(dict(backups[0]))
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 3)
        self.assertNotIn(_slug(0), sv.deletes)

    async def test_just_created_backup_is_never_deleted(self) -> None:
        # Fechas desordenadas: el recién creado tiene la fecha MÁS ANTIGUA
        # (reloj del Supervisor corregido). Aun así no se borra.
        entradas, backups = self._cinco()
        backups[0]["date"] = _iso(_AHORA - 30 * 86400)
        entradas[0]["launched_at"] = _AHORA
        self._anotar(entradas)
        sv = _Supervisor(backups)
        await sr.apply_retention(sv, 1, recien_creado=entradas[0]["name"])
        self.assertNotIn(_slug(0), sv.deletes)
        self.assertEqual(len(sv.deletes), 4)

    async def test_o_never_raises(self) -> None:
        class _Roto:
            async def sv_request(self, *a: Any, **k: Any) -> Any:
                raise ValueError("inesperado")

        entradas, _ = self._cinco()
        self._anotar(entradas)
        resumen = await sr.apply_retention(_Roto(), 1)
        self.assertEqual(resumen["deleted"], [])
        with patch.object(sr, "_cargar", side_effect=RuntimeError("x")):
            resumen = await sr.apply_retention(_Supervisor([]), 1)
        self.assertIn("error", resumen)

    async def test_p_log_event_has_deleted_kept_and_exclusions(self) -> None:
        entradas, backups = self._cinco()
        backups[4]["protected"] = True
        self._anotar(entradas)
        sv = _Supervisor(backups)
        with patch.object(sr, "logger") as log:
            await sr.apply_retention(sv, 2)
        llamadas = [c for c in log.info.call_args_list
                    if c.args and c.args[0] == "safety_backup_retention_done"]
        self.assertEqual(len(llamadas), 1)
        kw = llamadas[0].kwargs
        self.assertEqual(kw["deleted"], [entradas[0]["name"], entradas[1]["name"]])
        self.assertEqual(kw["kept"], [entradas[3]["name"], entradas[2]["name"]])
        self.assertEqual(kw["excluded"], [{"name": entradas[4]["name"], "reason": "protected"}])


# ── T050: enganches ───────────────────────────────────────────────────────────


class TestEnganches(unittest.IsolatedAsyncioTestCase):
    """`maybe_trigger_safety_backup`, `sv_create_safety_backup` y `register_write`."""

    def setUp(self) -> None:
        import hermes.tools.backups as backups

        self.b = backups
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.ruta = base / "safety_backups.json"
        self._patches = [
            patch.object(sr, "LEDGER_PATH", self.ruta),
            patch.object(backups, "_SAFETY_BACKUP_STATE_PATH", base / "last.json"),
        ]
        for p in self._patches:
            p.start()
        self.reloj = [time.time()]

        async def _dormir(segundos: float) -> None:
            self.reloj[0] += segundos

        self._patch_time = patch("time.time", side_effect=lambda: self.reloj[0])
        self._patch_sleep = patch("asyncio.sleep", side_effect=_dormir)
        self._patch_time.start()
        self._patch_sleep.start()
        backups._save_safety_state({backups._MARCA: self.reloj[0] - 31 * 60})

    def tearDown(self) -> None:
        self._patch_sleep.stop()
        self._patch_time.stop()
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _entradas(self) -> list[dict[str, Any]]:
        return json.loads(self.ruta.read_text(encoding="utf-8"))["entries"]

    async def _disparar(self, sv: Any, keep: int) -> Any:
        from hermes.fs_write import maybe_trigger_safety_backup

        return await maybe_trigger_safety_backup(
            sv, safety_backup_window_minutes=30, enabled=True, keep=keep)

    async def test_a_auto_success_records_confirms_and_prunes_once(self) -> None:
        sv = _Supervisor([], jobs={"job1": {"done": True, "errors": [],
                                            "reference": "aaaa0001"}},
                         post={"job_id": "job1"})
        with patch.object(sr, "apply_retention", new=AsyncMock(return_value={})) as ret:
            result = await self._disparar(sv, keep=1)
        self.assertIsNone(result)
        [e] = self._entradas()
        self.assertEqual(e["origin"], "auto")
        self.assertEqual(e["slug"], "aaaa0001")
        self.assertEqual(e["confirmed_by"], "job_reference")
        ret.assert_awaited_once()
        self.assertEqual(ret.await_args.args[1], 1)
        self.assertEqual(ret.await_args.kwargs["recien_creado"], e["name"])

    async def test_a_real_pruning_after_auto_success(self) -> None:
        # Extremo a extremo: un safety backup viejo anotado y confirmado se
        # borra; el recién creado, no.
        viejo = self.reloj[0] - 86400
        nombre_viejo = _nombre(viejo)
        self.ruta.write_text(json.dumps({"version": 1, "entries": [{
            "name": nombre_viejo, "job_id": None, "launched_at": viejo,
            "origin": "auto", "slug": "0ld00001", "confirmed_by": "job_reference"}]}),
            encoding="utf-8")
        sv = _Supervisor([], jobs={"job1": {"done": True, "errors": [],
                                            "reference": "aaaa0001"}},
                         post={"job_id": "job1"})

        async def _post_y_listado(method, path, **kw):
            if method == "GET" and path == "/backups":
                [nuevo] = [e for e in self._entradas() if e["slug"] == "aaaa0001"]
                return {"backups": [
                    _backup("0ld00001", nombre_viejo, viejo + 30),
                    _backup("aaaa0001", nuevo["name"], self.reloj[0]),
                ]}
            return await _Supervisor.sv_request(sv, method, path, **kw)

        sv.sv_request = _post_y_listado  # type: ignore[method-assign]
        result = await self._disparar(sv, keep=1)
        self.assertIsNone(result)
        self.assertEqual(sv.deletes, ["0ld00001"])

    async def test_b_failed_job_does_not_prune_and_rejects_write(self) -> None:
        sv = _Supervisor([], jobs={"job1": {"done": True, "reference": "aaaa0001",
                                            "errors": [{"message": "no space"}]}},
                         post={"job_id": "job1"})
        with patch.object(sr, "apply_retention", new=AsyncMock(return_value={})) as ret:
            result = await self._disparar(sv, keep=1)
        self.assertIn("safety_backup_job_failed", result["error"])
        ret.assert_not_awaited()
        self.assertEqual(self._entradas(), [])

    async def test_c_retention_failure_does_not_block_write(self) -> None:
        sv = _Supervisor([], jobs={"job1": {"done": True, "errors": [],
                                            "reference": "aaaa0001"}},
                         post={"job_id": "job1"})
        with patch.object(sr, "apply_retention",
                          new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await self._disparar(sv, keep=1)
        self.assertIsNone(result)

    async def test_c_ledger_failure_does_not_block_write(self) -> None:
        sv = _Supervisor([], jobs={"job1": {"done": True, "errors": [],
                                            "reference": "aaaa0001"}},
                         post={"job_id": "job1"})
        with patch.object(sr, "record_launch", new=AsyncMock(side_effect=OSError("ro"))), \
             patch.object(sr, "confirm_from_job", new=AsyncMock(side_effect=OSError("ro"))):
            result = await self._disparar(sv, keep=1)
        self.assertIsNone(result)

    async def test_d_pending_resolved_ok_on_next_call_also_prunes(self) -> None:
        self.b._save_safety_state({
            "pending_job_id": "job1",
            "pending_started_at": self.reloj[0] - 60,
            "pending_backup_name": "hermes-safety-20261114T083000Z",
        })
        await sr.record_launch("hermes-safety-20261114T083000Z", "job1", origin="auto")
        sv = _Supervisor([], jobs={"job1": {"done": True, "errors": [],
                                            "reference": "aaaa0001"}})
        with patch.object(sr, "apply_retention", new=AsyncMock(return_value={})) as ret:
            result = await self._disparar(sv, keep=2)
        self.assertIsNone(result)
        ret.assert_awaited_once()
        self.assertEqual(ret.await_args.args[1], 2)
        self.assertEqual(self._entradas()[0]["slug"], "aaaa0001")

    async def test_d_pending_failed_drops_entry_without_pruning(self) -> None:
        self.b._save_safety_state({
            "pending_job_id": "job1",
            "pending_started_at": self.reloj[0] - 60,
            "pending_backup_name": "hermes-safety-20261114T083000Z",
        })
        await sr.record_launch("hermes-safety-20261114T083000Z", "job1", origin="auto")
        sv = _Supervisor([], jobs={"job1": {"done": True, "reference": None,
                                            "errors": [{"message": "x"}]}})
        with patch.object(sr, "apply_retention", new=AsyncMock(return_value={})) as ret:
            result = await self._disparar(sv, keep=2)
        self.assertIn("safety_backup_job_failed", result["error"])
        ret.assert_not_awaited()
        self.assertEqual(self._entradas(), [])

    async def test_sync_response_with_slug_is_confirmed(self) -> None:
        sv = _Supervisor([], post={"slug": "aaaa0002"})
        with patch.object(sr, "apply_retention", new=AsyncMock(return_value={})) as ret:
            result = await self._disparar(sv, keep=3)
        self.assertIsNone(result)
        [e] = self._entradas()
        self.assertEqual((e["slug"], e["confirmed_by"]), ("aaaa0002", "sync_response"))
        ret.assert_awaited_once()

    async def test_disabled_does_not_touch_ledger(self) -> None:
        from hermes.fs_write import maybe_trigger_safety_backup

        sv = _Supervisor([])
        self.assertIsNone(await maybe_trigger_safety_backup(sv, 30, keep=3))
        self.assertFalse(self.ruta.exists())
        self.assertEqual(sv.peticiones, [])

    async def test_e_sv_create_safety_backup_records_tool_origin_and_never_deletes(self) -> None:
        from hermes.tools import backups as backups_mod

        class _MCP:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def tool(self):
                def deco(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return deco

        mcp = _MCP()
        # Hay safety backups de sobra anotados: aun así la tool no poda.
        entradas = [{"name": _nombre(_AHORA - i * 3600), "job_id": None,
                     "launched_at": _AHORA - i * 3600, "origin": "auto",
                     "slug": _slug(i), "confirmed_by": "job_reference"} for i in range(1, 6)]
        self.ruta.write_text(json.dumps({"version": 1, "entries": entradas}), encoding="utf-8")
        sv = _Supervisor([_backup(e["slug"], e["name"], e["launched_at"]) for e in entradas],
                         post={"job_id": "job9"})
        backups_mod.register(mcp, sv)
        with patch.object(backups_mod, "_track_job", new=AsyncMock()):
            result = await mcp.tools["sv_create_safety_backup"]()
        self.assertEqual(result["job_id"], "job9")
        self.assertEqual(sv.deletes, [])
        self.assertEqual([m for m, _ in sv.peticiones], ["POST"])
        nueva = [e for e in self._entradas() if e["job_id"] == "job9"]
        self.assertEqual(len(nueva), 1)
        self.assertEqual(nueva[0]["origin"], "tool")
        self.assertEqual(nueva[0]["name"], result["backup_name"])
        doc = mcp.tools["sv_create_safety_backup"].__doc__
        self.assertIn("safety_backup_keep", doc)

    async def test_f_register_write_passes_keep_to_safety_backup(self) -> None:
        from hermes.tools import filesystem_write as fw

        class _MCP:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def tool(self, *a: Any, **k: Any):
                def deco(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return deco

        mcp = _MCP()
        fw.register_write(mcp, object(), safety_backup_enabled=True, safety_backup_keep=2)
        disparo = AsyncMock(return_value={"error": "safety_backup_failed: parar aquí"})
        with patch.object(fw, "maybe_trigger_safety_backup", new=disparo), \
             patch.object(fw, "reserve_write_slot", new=AsyncMock()), \
             patch.object(fw, "resolve_confirmation_token",  # 1.1.2 (spec 007)
                          new=AsyncMock(return_value=(
                              True, "", {"path": "notas.txt", "content": "hola"}))), \
             patch.object(fw, "complete_confirmation_token", new=AsyncMock()):
            await mcp.tools["fs_write_file"]("notas.txt", "hola", confirmation_token="t")
        disparo.assert_awaited_once()
        self.assertEqual(disparo.await_args.kwargs["keep"], 2)

    def test_f_register_write_default_keep_is_3(self) -> None:
        import inspect

        from hermes.tools import filesystem_write as fw

        firma = inspect.signature(fw.register_write)
        self.assertEqual(firma.parameters["safety_backup_keep"].default, 3)
        fuente = inspect.getsource(fw.register_write)
        self.assertEqual(fuente.count("maybe_trigger_safety_backup("), 5)
        self.assertEqual(fuente.count("keep=safety_backup_keep"), 5)


# ── Lock del safety backup (CodeQL: `_SAFETY_LOCK_LOOP` sin uso) ──────────────


class TestSafetyLockPorBucle(unittest.TestCase):
    """El lock del safety backup se recrea si cambia el bucle de eventos.

    Un `asyncio.Lock` con espera se ata al bucle donde se usa por primera vez;
    usado con contención desde otro bucle lanza `RuntimeError`. En producción
    hay un solo bucle, pero cada test asíncrono crea el suyo.
    """

    def test_lock_works_with_contention_in_two_loops(self) -> None:
        import hermes.fs_write as fsw

        async def _uso() -> int:
            lock = fsw._safety_lock()
            self.assertIs(lock, fsw._safety_lock())

            async def _tomar() -> None:
                async with lock:
                    await asyncio.sleep(0)

            await asyncio.gather(_tomar(), _tomar())
            return id(lock)

        primero = asyncio.run(_uso())
        segundo = asyncio.run(_uso())
        self.assertNotEqual(primero, segundo)


if __name__ == "__main__":
    unittest.main()

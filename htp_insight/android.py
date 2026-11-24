"""Local Android QAIRT capture. The CLI owns the device transport and Core owns ingestion."""
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from .core import Core, atomic_write, digest, encode
from .qnn import optrace_onnx_mappings

MODES = {
    "basic": ("qnn-viewer-csv-v2.50", "profile.csv"),
    "detailed": ("qnn-viewer-csv-v2.50", "profile.csv"),
    "linting": ("qnn-linting-chrome-v2.50", "profile.json"),
    "optrace": ("qnn-optrace-chrome-v2.50", "trace.json"),
}
TEMP_PATH = re.compile(r"/data/local/tmp/htp-insight\.[a-zA-Z0-9]+")


class AndroidRunner:
    def __init__(self, adb, serial, sdk, arch, timeout):
        self.command = [adb, *(['-s', serial] if serial else [])]
        self.sdk = Path(sdk).resolve()
        self.arch = arch.lower()
        self.timeout = timeout

    def adb(self, argv, log=None):
        result = subprocess.run(self.command + argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=self.timeout, check=False)
        if log is not None:
            atomic_write(log, result.stdout)
        output = result.stdout.decode(errors="replace").strip()
        if result.returncode:
            raise RuntimeError(f"adb {argv[0]} returned {result.returncode}: {output[-1800:]}")
        return output

    def shell(self, argv, log=None):
        return self.adb(["shell", shlex.join(argv)], log)

    def tools(self, mode, is_dlc):
        binaries = ["qnn-net-run", "qnn-profile-viewer"]
        libraries = ["libQnnHtp.so", "libQnnSystem.so", f"libQnnHtp{self.arch.upper()}Stub.so"]
        if is_dlc:
            libraries.extend(("libQnnModelDlc.so", "libQnnHtpPrepare.so"))
        if mode == "linting":
            libraries.extend(("libQnnHtpNetRunExtensions.so", "libQnnChrometraceProfilingReader.so"))
        if mode == "optrace":
            libraries.append("libQnnHtpOptraceProfilingReader.so")
        return ([(self.sdk / "bin/aarch64-android" / name) for name in binaries]
                + [(self.sdk / "lib/aarch64-android" / name) for name in libraries]
                + [self.sdk / f"lib/hexagon-{self.arch}/unsigned/libQnnHtp{self.arch.upper()}Skel.so"])

    def capture(self, core: Core, args):
        if not re.fullmatch(r"v\d+", self.arch):
            raise ValueError("Expected a Hexagon architecture such as v73")
        if not 0 <= args.warmup < args.runs <= 1000:
            raise ValueError("Expected 0 <= warmup < runs <= 1000")
        graph = core.graph(args.model_id)
        model = args.model.resolve()
        is_dlc = model.suffix.lower() == ".dlc"
        if not model.is_file() or model.suffix.lower() not in {".dlc", ".bin"}:
            raise ValueError("Expected a local .dlc or .bin")
        if args.mode == "optrace" and (is_dlc or args.schematic is None):
            raise ValueError("Optrace requires a context .bin and its matching schematic")
        if args.framework_csv and (args.mode != "optrace" or not args.trace_dlc):
            raise ValueError("Framework CSV requires Optrace and the corresponding DLC")
        if args.mode != "optrace" and (args.trace_dlc or args.schematic):
            raise ValueError("Schematic and traceback DLC apply to Optrace")
        if args.trace_dlc is not None and args.trace_dlc.suffix.lower() != ".dlc":
            raise ValueError("Traceback DLC must be a .dlc")

        inputs = {}
        for item in args.input:
            name, sep, filename = item.partition("=")
            path = Path(filename).resolve()
            if not sep or not name or any(char.isspace() for char in name) or name in inputs or not path.is_file():
                raise ValueError("Use unique --input tensor_name=local.raw entries")
            inputs[name] = path
        if set(inputs) != set(graph.inputs):
            raise ValueError(f"Input names must match ONNX inputs: {', '.join(graph.inputs)}")

        tools = self.tools(args.mode, is_dlc)
        for path in [*tools, *(p for p in (args.schematic, args.trace_dlc, args.framework_csv) if p is not None)]:
            if not path.is_file():
                raise FileNotFoundError(f"Missing QAIRT component or evidence: {path}")
        if self.adb(["get-state"]) != "device":
            raise RuntimeError("No authorized Android device")
        device = {key: self.shell(["getprop", prop]) or None for key, prop in {
            "manufacturer": "ro.product.manufacturer", "model": "ro.product.model",
            "soc": "ro.soc.model", "os_version": "ro.build.version.release", "abi": "ro.product.cpu.abi",
        }.items()}
        if device["abi"] != "arm64-v8a":
            raise RuntimeError(f"Expected Android arm64-v8a, got {device['abi']}")
        device.update(os="Android", hexagon=self.arch.upper())

        destination = core.root / "android-runs"
        destination.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="qnn-", dir=destination))
        remote = self.shell(["mktemp", "-d", "/data/local/tmp/htp-insight.XXXXXX"])
        if not TEMP_PATH.fullmatch(remote):
            raise RuntimeError("ADB returned an unexpected directory")
        try:
            return self._run(core, args, work, remote, tools, device, model, inputs, is_dlc)
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{exc}\nCapture logs: {work}") from exc
        finally:
            if not args.keep_device_files:
                try:
                    self.shell(["rm", "-rf", remote], work / "cleanup.log")
                except (RuntimeError, OSError, subprocess.TimeoutExpired):
                    pass

    def _run(self, core, args, work, remote, tools, device, model, inputs, is_dlc):
        def push(source, name):
            self.adb(["push", str(source), f"{remote}/{name}"])

        for tool in tools:
            push(tool, tool.name)
        self.shell(["chmod", "755", f"{remote}/qnn-net-run", f"{remote}/qnn-profile-viewer"])
        version_output = self.shell([f"{remote}/qnn-net-run", "--version"], work / "versions.log")
        version = re.search(r"\bv2\.50\.\S+", version_output)
        if not version:
            raise RuntimeError("Expected the QAIRT 2.50 Android runtime")

        state = {"files": {}, "native_io": args.native_io}
        input_entries = []
        for index, (name, path) in enumerate(sorted(inputs.items())):
            dest = f"input-{index}.raw"
            push(path, dest)
            input_entries.append(f"{name}:={remote}/{dest}")
            state["files"][name] = digest(path.read_bytes())
        atomic_write(work / "input_list.txt", ("\n".join(input_entries) + "\n").encode())
        push(work / "input_list.txt", "input_list.txt")
        filename = "model.dlc" if is_dlc else "model.bin"
        push(model, filename)

        model_args = ["--model", "./libQnnModelDlc.so", "--dlc_path", "./model.dlc"] if is_dlc else [
            "--retrieve_context", "./model.bin",
        ]
        profile_args = ["--profiling_level", args.mode]
        reader = []
        if args.mode == "linting":
            atomic_write(work / "htp.json", encode({"devices": [{"profiling_level": "linting"}]}))
            atomic_write(work / "backend.json", encode({
                "backend_extensions": {"shared_library_path": "./libQnnHtpNetRunExtensions.so",
                                       "config_file_path": "./htp.json"},
            }))
            for name in ("htp.json", "backend.json"):
                push(work / name, name)
            profile_args = ["--profiling_level", "backend", "--config_file", "./backend.json"]
            reader = ["--reader", "./libQnnChrometraceProfilingReader.so"]
        elif args.mode == "optrace":
            push(args.schematic, "schematic.bin")
            if args.trace_dlc:
                push(args.trace_dlc, "traceback.dlc")
            atomic_write(work / "features.json", encode({"features": {
                "htp_json": True, "traceback": True, "qhas_json": True,
                "enable_input_output_flow_events": True, "enable_sequencer_flow_events": True,
            }}))
            push(work / "features.json", "features.json")
            profile_args = ["--profiling_level", "detailed", "--profiling_option", "optrace"]
            reader = ["--reader", "./libQnnHtpOptraceProfilingReader.so", "--schematic", "./schematic.bin",
                      "--config", "./features.json"]
            if args.trace_dlc:
                reader.extend(("--dlc", "./traceback.dlc"))

        environment = [f"LD_LIBRARY_PATH={remote}:/vendor/lib64",
                       f"ADSP_LIBRARY_PATH={remote};/vendor/lib/rfsa/adsp;/vendor/dsp/cdsp"]
        prefix = f"cd {shlex.quote(remote)} && "
        runner = ["env", *environment, "./qnn-net-run", "--backend", "./libQnnHtp.so", *model_args, *profile_args,
                  "--input_list", "./input_list.txt", "--output_dir", "./result", "--num_inferences", str(args.runs),
                  "--keep_num_outputs", "1", "--perf_profile", args.perf_profile, "--log_level", "info"]
        if args.native_io:
            runner.extend(("--use_native_input_files", "--use_native_output_files"))
        self.adb(["shell", prefix + shlex.join(runner)], work / "run.log")

        format, artifact_file = MODES[args.mode]
        command = ["env", *environment, "./qnn-profile-viewer", "--input_log", "./result/qnn-profiling-data_0.log",
                   *reader, "--output", f"./result/{artifact_file}"]
        self.adb(["shell", prefix + shlex.join(command)], work / "viewer.log")
        self.adb(["pull", f"{remote}/result/.", str(work)], work / "pull.log")
        raw = (work / artifact_file).read_bytes()
        mappings = None
        if args.framework_csv:
            mappings = optrace_onnx_mappings(raw, args.framework_csv.read_bytes(), core.graph(args.model_id))
        conditions = {
            "input_sha256": digest(encode(state)), "inputs": state["files"], "native_io": args.native_io,
            "profiling_level": args.mode, "perf_profile": args.perf_profile,
            "capture_protocol": "qnn-net-run Android runner", "warmup": args.warmup, "runs": args.runs,
            "model_sha256": digest(model.read_bytes()), "model_format": "DLC" if is_dlc else "HTP context",
        }
        if format == "qnn-viewer-csv-v2.50":
            conditions["repeats"] = args.runs - args.warmup
        else:
            conditions["trace_runs"] = args.runs
        profile = core.save_profile(args.model_id, raw, format, "measured", "QNN HTP", version[0],
                                    device, conditions, mappings=mappings)
        attachments = []
        for name, evidence_format in (("trace_htp.json", "htp-graph-v1.0"),
                                      ("trace_qnn_htp_analysis_summary.json", "qhas-v1.0")):
            file = work / name
            if file.is_file():
                inbox = core.inbox / f"{work.name}-{file.name}"
                atomic_write(inbox, file.read_bytes())
                attachments.append(core.import_evidence(profile["id"], inbox.name, evidence_format, "measured"))
        manifest = {"capture": str(work), "profile": profile, "evidence": attachments,
                    "device_directory": remote if args.keep_device_files else None,
                    "runner_arguments": runner, "viewer_arguments": command}
        atomic_write(work / "capture.json", encode(manifest))
        return manifest

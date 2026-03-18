import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

import argparse
# Ensure core modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from drivers.InfinityEngine.resource_loader import ResourceLoader
from drivers.InfinityEngine.definitions.extensions import RESOURCE_TYPE_MAP_REV

class ResourceBenchmark:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.tasks_to_load = []
        self.sequential_results = None
        self.threaded_results = None
        self.sequential_time = 0
        self.threaded_time = 0

    def _load_single_resource(self, resref, restype, game, loader):
        if self.verbose:
            print(f"[{threading.current_thread().name}] Loading {resref}.{restype} for {game}...")
        try:
            resource = loader.load(resref=resref, restype=restype, game=game)
            if resource:
                if self.verbose:
                    print(f"[{threading.current_thread().name}] Successfully loaded {resref}.{restype}.")
                return resref, resource
            return resref, None
        except Exception as e:
            if self.verbose:
                print(f"[{threading.current_thread().name}] Error loading {resref}.{restype}: {e}")
            return resref, None

    def gather_tasks(self):
        loader = ResourceLoader()
        installations = loader.install_finder.find_all()
        if not installations:
            print("No Infinity Engine game installations found. Cannot run example.")
            return

        print(f"Found {len(installations)} installations: {', '.join(inst.game_id for inst in installations)}")

        print("\nConcurrently loading CHITIN.KEY for all games...")
        with ThreadPoolExecutor(max_workers=len(installations) or 1) as executor:
            list(executor.map(loader._load_chitin, [inst.game_id for inst in installations]))
        print("CHITIN.KEY loading complete.")

        print("\nFinding all ITM resources in loaded CHITIN.KEYs...")
        itm_type_code = RESOURCE_TYPE_MAP_REV.get("ITM")
        if itm_type_code is None:
            print("Error: ITM type code not found in definitions.")
            return

        for game_id, chitin in loader.chitins.items():
            if not chitin:
                continue

            all_resource_entries = chitin.sections.get("resource_entries", [])
            game_count = 0
            for entry in all_resource_entries:
                if entry.get("resource_type") == itm_type_code:
                    res_name = entry.get("resource_name", "").strip().upper()
                    if res_name:
                        self.tasks_to_load.append((res_name, "ITM", game_id))
                        game_count += 1
            print(f"  [{game_id}] Found {game_count} ITM resources.")

    def warm_up_cache(self):
        if not self.tasks_to_load:
            return
        print("\nPerforming an untimed sequential run to warm up OS file cache...")
        loader = ResourceLoader()
        self._run_sequential_internal(self.tasks_to_load, loader)
        print("Warm-up complete.")

    def run_sequential(self):
        if not self.tasks_to_load:
            print("No tasks gathered. Cannot run sequential test.")
            return
        loader = ResourceLoader()
        self.sequential_time, self.sequential_results = self._run_sequential_internal(self.tasks_to_load, loader)

    def _run_sequential_internal(self, tasks, loader):
        print("Running Sequential Test...") if self.verbose else None
        loaded_resources = {}
        start_time = time.perf_counter()
        for resref, restype, game in tasks:
            result_resref, resource_obj = self._load_single_resource(resref, restype, game, loader)
            if resource_obj:
                loaded_resources[(game, result_resref)] = resource_obj
        end_time = time.perf_counter()
        return end_time - start_time, loaded_resources

    def run_threaded(self, max_workers, progress_callback=None):
        if not self.tasks_to_load:
            print("No tasks gathered. Cannot run threaded test.")
            return
        loader = ResourceLoader()
        self.threaded_time, self.threaded_results = self._run_threaded_internal(self.tasks_to_load, loader, max_workers, progress_callback)

    def _run_threaded_internal(self, tasks, loader, max_workers, progress_callback=None):
        print(f"Running Threaded Test ({max_workers} workers)...") if self.verbose else None
        loaded_resources = {}
        start_time = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._load_single_resource, resref, restype, game, loader): (resref, restype, game)
                for resref, restype, game in tasks
            }
            if self.verbose:
                print("\nSubmitted all loading tasks. Waiting for results...")
            
            completed_count = 0
            total_tasks = len(futures)
            for future in as_completed(futures):
                resref, restype, game = futures[future]
                result_resref, resource_obj = future.result()
                if resource_obj:
                    loaded_resources[(game, result_resref)] = resource_obj
                
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total_tasks)
        end_time = time.perf_counter()
        return end_time - start_time, loaded_resources

    def print_summary(self, test_type, num_workers=None):
        if test_type == 'sequential':
            title = "Sequential Test (Hot Cache)"
            elapsed_time = self.sequential_time
            num_loaded = len(self.sequential_results) if self.sequential_results else 0
        elif test_type == 'threaded':
            title = f"Threaded Test ({num_workers} workers, Hot Cache)"
            elapsed_time = self.threaded_time
            num_loaded = len(self.threaded_results) if self.threaded_results else 0
        else:
            return

        print(f"\n--- {title} Summary ---")
        print(f"Total resources requested: {len(self.tasks_to_load)}")
        print(f"Total resources successfully loaded: {num_loaded}")
        print(f"Total time: {elapsed_time:.4f} seconds")
        if elapsed_time > 0:
            rps = len(self.tasks_to_load) / elapsed_time
            print(f"Resources per second: {rps:.2f}")

def console_progress_bar(completed, total):
    bar_length = 40
    percent = completed / total
    filled_length = int(bar_length * percent)
    bar = '=' * filled_length + '-' * (bar_length - filled_length)
    sys.stdout.write(f'\r[{bar}] {percent:.1%} ({completed}/{total})')
    sys.stdout.flush()
    if completed == total:
        sys.stdout.write('\n')

def main():
    parser = argparse.ArgumentParser(description="Benchmark concurrent vs sequential resource loading.")
    parser.add_argument('--test', type=str, choices=['threaded', 'sequential', 'both'], default='both', help='Which test to run.')
    parser.add_argument('--threads', type=int, default=8, help='Number of worker threads for the threaded test.')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose print statements during loading.')
    args = parser.parse_args()

    benchmark = ResourceBenchmark(verbose=args.verbose)

    print("\n" + "="*50)
    print("INITIALIZING BENCHMARK")
    print("="*50)
    benchmark.gather_tasks()
    if not benchmark.tasks_to_load:
        return
    
    print(f"\nTotal ITM resources found across all games: {len(benchmark.tasks_to_load)}")

    # Warm up the OS file cache to ensure fair "hot cache" comparison for both tests.
    benchmark.warm_up_cache()

    if args.test in ['sequential', 'both']:
        print("\n" + "="*50)
        print("INITIALIZING FOR SEQUENTIAL TEST (HOT CACHE)")
        print("="*50)
        benchmark.run_sequential()
        benchmark.print_summary('sequential')
            
    if args.test in ['threaded', 'both']:
        print("\n" + "="*50)
        print("INITIALIZING FOR THREADED TEST (HOT CACHE)")
        print("="*50)
        # Only use progress bar if not in verbose mode to avoid console scrambling
        cb = console_progress_bar if not args.verbose else None
        benchmark.run_threaded(max_workers=args.threads, progress_callback=cb)
        benchmark.print_summary('threaded', num_workers=args.threads)

if __name__ == "__main__":
    main()

# Globe repaint measurements

The globe reuses the ordinary country and station drawing styles throughout a
paint. It changes them for an active country, selected station, or landing
highlight, then restores the ordinary style. Projection, marker order, depth
opacity, and hit testing use the same calculations.

Compared with `f133ed918591820d49c666923d724fcbd7d8d17f`, five paired runs on an
Intel Core i5-14400F with Qt 6.12.0 produced these mean paint-handler times:

| View | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| World, 1x | 4.107 ms | 3.791 ms | 7.7% |
| Regional, 3x | 2.700 ms | 2.512 ms | 7.0% |
| Deep zoom, 12x | 2.400 ms | 2.317 ms | 3.5% |

The world-view marker portion fell from 2.171 to 1.844 ms, a 15.0% reduction.
The test uses an 800 x 600 globe, all 177 bundled country features, and 5,000
deterministic synthetic stations. Each fresh process warms up for 60 frames and
measures 180 frames per view. Five runs per version provide 900
measured frames per view. Pair order alternates. Processes use CPU 0 and the
software/offscreen backend.

These are JavaScript paint-handler wall times, measured with millisecond timer
resolution. They exclude complete rasterization, texture upload, compositor
presentation, and input latency. They are not an FPS measurement. World-view
run means ranged from 4.089 to 4.144 ms before and 3.567 to 4.367 ms after.
One patched world-view run had an 8 ms 95th percentile; the other four had 4 ms.
The baseline runs each had a 5 ms 95th percentile. Tail latency is not claimed
to improve. The raw run summaries are in
[globe-brushes.json](../.github/pr-evidence/globe-brushes.json).

All 16 matching complete renders were byte-identical across eight views in
dark and light themes, including both poles, the dateline, and deep zoom.
Station hit testing matched at every sampled point. The focused regressions
also check active-style restoration: 5,000 markers with two active markers
need five fill-style writes instead of 5,000, and 100 countries with one active
country need nine style writes instead of 300.

To repeat one benchmark run from the repository root:

```bash
git show f133ed918591820d49c666923d724fcbd7d8d17f:Globe.qml > /tmp/radio-globe-before.qml
python3 tests/benchmark-globe.py --source /tmp/radio-globe-before.qml --cpu 0
python3 tests/benchmark-globe.py --cpu 0
```

Repeat the pair five times, reversing the order every other pair. Choose the
same allowed CPU for both versions. The script uses the installed Qt test
runner and Python standard library, creates temporary fixtures, and prints
JSON. It does not start playback or contact the network.

# Gait generation

Minimal installation for the gait generation in requirements.txt

## Generate one gait

TODO `gait_generator.py` is outdated, and its code is redundant with `auto_gait_generator.py`.

We need to either factorize the code, or just use `auto_gait_generator.py` with `-n 1`.

```bash
python3 gait_generator.py -n <name> <--mini> --dx X --dy Y --dt T --length L -o <output_dir>
```

## Generate multiple gaits

```bash
python3 auto_gait_generator.py -o <output_dir> -n <number> <--mini> --min_dx X --max_dx X --min_dy Y --max_dy Y --min_dt T --max_dt T --length L
```

## Replay a move

```bash
python3 replay_amp.py -f <path/.json>
```

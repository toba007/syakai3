def main():
    try:
        import sounddevice as sd
    except Exception as exc:
        raise SystemExit(f"sounddevice is not available: {exc}")

    print(sd.query_devices())
    print()
    print("Default device:")
    print(sd.default.device)


if __name__ == "__main__":
    main()

import matplotlib.pyplot as plt

def plot_results(results, out_path="experiment_plot.svg"):
    """Plot average time (ms) and average memory (MB) per configuration.

    `results` is a list of dicts with keys: `config`, `avg_time_ms`, `avg_mem_mb`.
    """
    if not results:
        raise ValueError("No results to plot")

    configs = [r["config"] for r in results]
    times = [r.get("avg_time_ms", 0.0) for r in results]
    mems = [r.get("avg_mem_mb", -1.0) for r in results]

    fig, ax1 = plt.subplots(figsize=(10, 5))

    x = range(len(configs))
    ax1.bar(x, times, color="#1f77b4", alpha=0.7)
    ax1.set_xlabel("Configuração experimental")
    ax1.set_ylabel("Tempo médio (ms)", color="#1f77b4")
    ax1.set_xticks(x)
    ax1.set_xticklabels(configs)

    ax2 = ax1.twinx()
    ax2.plot(x, mems, color="#ff7f0e", marker="o")
    ax2.set_ylabel("Uso médio de memória (MB)", color="#ff7f0e")

    plt.title("Tempo médio de transação e uso de memória por configuração")
    plt.tight_layout()
    plt.savefig(out_path, format="svg")
    plt.close(fig)

    print("Plot saved to", out_path)

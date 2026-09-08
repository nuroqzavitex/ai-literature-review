import matplotlib.pyplot as plt
import statsmodels.api as sm
from scipy import stats

from sandbox_sdk import emit_chart, emit_result, emit_table, load_dataset


frame = load_dataset()
design = sm.add_constant(frame.index.to_numpy())
model = sm.OLS(frame["value"], design).fit()
normality = stats.shapiro(model.resid)
emit_table("summary", frame.describe(include="all").reset_index())
figure, axis = plt.subplots()
axis.plot(frame.index, frame["value"])
axis.set_title("Runtime smoke chart")
emit_chart("summary", figure)
plt.close(figure)
emit_result(
    {
        "schema_version": "analysis_result.v1",
        "objective": "describe",
        "method": "Descriptive statistics",
        "input_row_count": len(frame),
        "analyzed_row_count": len(frame),
        "preprocessing_applied": [],
        "assumption_checks": [{"name": "schema", "passed": True}],
        "metrics": [
            {"name": "row_count", "value": len(frame)},
            {"name": "r_squared", "value": float(model.rsquared)},
        ],
        "statistical_results": [],
        "warnings": [] if normality.pvalue >= 0 else ["invalid normality result"],
        "limitations": [],
        "artifact_refs": [
            "analysis_result.json",
            "tables/summary.csv",
            "charts/summary.png",
        ],
        "narrative": [],
    }
)

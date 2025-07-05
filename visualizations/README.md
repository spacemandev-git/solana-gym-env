# Solana Gym Visualizations

This directory contains interactive HTML dashboards for analyzing agent performance and trajectories.

## 📊 Available Dashboards

- **`dashboard.html`** - Main performance dashboard
- **`trajectory_dashboard.html`** - Trajectory analysis and visualization
- **`jupiter_analysis.html`** - Jupiter protocol discovery analysis
- **`learning_curve.html`** - Agent learning curve visualization
- **`skill_efficiency.html`** - Skill execution efficiency metrics
- **`transaction_browser.html`** - Browse and analyze individual transactions
- **`transaction_complexity_analysis.html`** - Transaction complexity metrics
- **`comprehensive_dashboard.html`** - All-in-one comprehensive view

## 🚀 Usage

Simply open any HTML file in your web browser:

```bash
open visualizations/dashboard.html
```

Or serve them with a local web server:

```bash
cd visualizations
python -m http.server 8000
# Then visit http://localhost:8000
```

## 📈 Features

These dashboards provide:
- Real-time trajectory visualization
- Protocol discovery tracking
- Skill success rate analysis
- Transaction complexity metrics
- Learning efficiency curves
- Interactive filtering and exploration

## 🔄 Updating Data

The visualizations read from trajectory JSON files. To update with new data:
1. Run your agent to generate new trajectory data
2. Ensure the data is saved to the expected location
3. Refresh the dashboard in your browser
package sh.colak.xrconsole.recorder;

import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

public final class RecordTileService extends TileService implements RecState.Listener {
    @Override public void onStartListening() {
        RecState.I.add(this);
        paint();
    }

    @Override public void onStopListening() {
        RecState.I.remove(this);
    }

    @Override public void onClick() {
        RecState.Phase p = RecState.I.phase;
        if (p == RecState.Phase.RECORDING || p == RecState.Phase.STARTING) {
            RecordService.stop(this);
        } else {
            RecordService.start(this, RecordEngine.DEFAULT_SEGMENT_MS, 0);
        }
    }

    @Override public void onRecState() { paint(); }

    private void paint() {
        Tile t = getQsTile();
        if (t == null) return;
        boolean on = RecState.I.phase == RecState.Phase.RECORDING;
        t.setLabel("XR REC");
        t.setState(on ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        t.updateTile();
    }
}

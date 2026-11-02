package com.manaskhare.sanae.watch

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import androidx.wear.protolayout.ActionBuilders
import androidx.wear.protolayout.ColorBuilders.argb
import androidx.wear.protolayout.DeviceParametersBuilders.DeviceParameters
import androidx.wear.protolayout.LayoutElementBuilders
import androidx.wear.protolayout.ModifiersBuilders
import androidx.wear.protolayout.ResourceBuilders
import androidx.wear.protolayout.TimelineBuilders
import androidx.wear.protolayout.material.Chip
import androidx.wear.protolayout.material.ChipColors
import androidx.wear.protolayout.material.Colors
import androidx.wear.protolayout.material.Text
import androidx.wear.protolayout.material.Typography
import androidx.wear.protolayout.material.layouts.PrimaryLayout
import androidx.wear.tiles.RequestBuilders
import androidx.wear.tiles.TileBuilders
import androidx.wear.tiles.TileService
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.MonochromaticImage
import androidx.wear.watchface.complications.data.MonochromaticImageComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.data.SmallImage
import androidx.wear.watchface.complications.data.SmallImageComplicationData
import androidx.wear.watchface.complications.data.SmallImageType
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

private const val RES = "1"
private const val NAVY = 0xFF060A13.toInt()
private const val GREY = 0xFF94A3B8.toInt()

/** Swipe to it from the watch face: the next few things today and a "Talk" button. */
class TodayTile : TileService() {
    override fun onTileRequest(request: RequestBuilders.TileRequest): ListenableFuture<TileBuilders.Tile> {
        Phone.requestGlance(this)                     // fresh list arrives later and asks for a redraw
        val glance = WatchHub.glance.value ?: Store(this).glance()
        val layout = layout(this, request.deviceConfiguration, glance, System.currentTimeMillis())
        return Futures.immediateFuture(
            TileBuilders.Tile.Builder()
                .setResourcesVersion(RES)
                .setFreshnessIntervalMillis(15 * 60_000L)
                .setTileTimeline(TimelineBuilders.Timeline.fromLayoutElement(layout))
                .build()
        )
    }

    override fun onTileResourcesRequest(request: RequestBuilders.ResourcesRequest): ListenableFuture<ResourceBuilders.Resources> =
        Futures.immediateFuture(ResourceBuilders.Resources.Builder().setVersion(RES).build())

    private fun layout(context: Context, device: DeviceParameters, glance: Glance?, now: Long): LayoutElementBuilders.LayoutElement {
        val talk = ModifiersBuilders.Clickable.Builder()
            .setId("talk")
            .setOnClick(ActionBuilders.LaunchAction.Builder()
                .setAndroidActivity(ActionBuilders.AndroidActivity.Builder()
                    .setPackageName(context.packageName)
                    .setClassName(TalkActivity::class.java.name)
                    .addKeyToExtraMapping(TalkActivity.EXTRA_LISTEN, ActionBuilders.booleanExtra(true))
                    .build())
                .build())
            .build()
        val items = glance?.items.orEmpty().take(3)
        val column = LayoutElementBuilders.Column.Builder()
            .setHorizontalAlignment(LayoutElementBuilders.HORIZONTAL_ALIGN_CENTER)
        if (items.isEmpty()) {
            column.addContent(line(context, if (glance == null) "Open Sanae once on the watch" else "Nothing else today",
                                   Typography.TYPOGRAPHY_CAPTION1, GREY))
        }
        for (it in items) {
            column.addContent(line(context, it.title, Typography.TYPOGRAPHY_CAPTION1, 0xFFFFFFFF.toInt()))
            column.addContent(line(context, whenLabel(it, now), Typography.TYPOGRAPHY_CAPTION2, GREY))
        }
        val colors = Colors(Faces.CYAN.toInt(), NAVY, 0xFF1E293B.toInt(), 0xFFFFFFFF.toInt())
        return PrimaryLayout.Builder(device)
            .setResponsiveContentInsetEnabled(true)
            .setPrimaryLabelTextContent(line(context, "Sanae", Typography.TYPOGRAPHY_CAPTION1, Faces.CYAN.toInt()))
            .setContent(column.build())
            .setPrimaryChipContent(
                Chip.Builder(context, talk, device)
                    .setPrimaryLabelContent("Talk")
                    .setChipColors(ChipColors.primaryChipColors(colors))
                    .build()
            )
            .build()
    }

    private fun line(context: Context, text: String, typography: Int, color: Int) =
        Text.Builder(context, text)
            .setTypography(typography)
            .setColor(argb(color))
            .setMaxLines(1)
            .build()
}

/** A watch-face complication that opens Sanae already listening. */
class TalkComplication : SuspendingComplicationDataSourceService() {
    override fun getPreviewData(type: ComplicationType): ComplicationData? = data(type)

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData? = data(request.complicationType)

    private fun data(type: ComplicationType): ComplicationData? {
        val tap = PendingIntent.getActivity(
            this, 0,
            Intent(this, TalkActivity::class.java).putExtra(TalkActivity.EXTRA_LISTEN, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val about = PlainComplicationText.Builder("Talk to Sanae").build()
        val mic = MonochromaticImage.Builder(Icon.createWithResource(this, R.drawable.ic_mic)).build()
        return when (type) {
            ComplicationType.SHORT_TEXT ->
                ShortTextComplicationData.Builder(PlainComplicationText.Builder("Sanae").build(), about)
                    .setMonochromaticImage(mic).setTapAction(tap).build()
            ComplicationType.MONOCHROMATIC_IMAGE ->
                MonochromaticImageComplicationData.Builder(mic, about).setTapAction(tap).build()
            ComplicationType.SMALL_IMAGE ->
                SmallImageComplicationData.Builder(
                    SmallImage.Builder(Icon.createWithResource(this, R.drawable.face_neutral), SmallImageType.PHOTO).build(), about)
                    .setTapAction(tap).build()
            else -> null
        }
    }
}

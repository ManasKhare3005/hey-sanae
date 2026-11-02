# Release builds run through R8 so Compose and the other libraries are optimised (typing and
# scrolling lagged without it). The app's own classes are kept whole and names stay readable,
# so crash reports (CrashLog.kt) still point at real lines.
-dontobfuscate
-keep class com.manaskhare.sanae.** { *; }
-keepattributes SourceFile,LineNumberTable

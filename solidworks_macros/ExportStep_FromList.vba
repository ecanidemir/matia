' =========================================================================
' STEP EXPORT - LISTE MODU v1-steplist (SolidWorks 2014 uyumlu)
' Turedi: ExportFlatPattern_FromList (v2-list motoru: anlik iz, dogrulamali
' kapatma, son supurme, kir-bayragi iadesi aynen korunur).
' Fark: DXF duz-desan YOK, sac kontrolu YOK. Listedeki her dosya (sldprt/sldasm,
' uzantili/uzantisiz) gorunmez acilir, STEP_EXPORT\<uretim_sekli>\<DosyaAdi>.step
' olarak kaydedilir (uretim_sekli custom property'sinden, bos ise Diger), kapatilir.
' Liste: step_liste.txt (tek sutun dosya adi, ornek: M3TLLN01). Konfig
' degistirilmez, aktif konfig kullanilir. Tur siniri YOK (USE_BATCH_LIMIT=False),
' SKIP_EXISTING ile kalinan yerden devam edilir.
' =========================================================================
Option Explicit

' --- AYARLAR ---
Const BASE_DIR As String = "D:\Ortak Drive'lar\Matia Mobility\2000_TECHNICAL\2300_3D_CAD\2310_TekRMD_Sldwrks"
Const LIST_NAME As String = "step_liste.txt"
Const STEP_SUBDIR As String = "STEP_EXPORT"
Const SKIP_EXISTING_FILES As Boolean = True
Const STATUS_EVERY As Long = 5   ' her N parcada DoEvents (nefes)
Const FILES_PER_RUN As Long = 50 ' USE_BATCH_LIMIT kapaliyken kullanilmaz (yedekte durur)
Const USE_BATCH_LIMIT As Boolean = False ' False = tur siniri YOK, liste sonuna kadar gider
Dim gNRun As Long ' bu kostuda acilan dosya sayaci

Dim swApp As SldWorks.SldWorks
Dim gLog As Collection
Dim gOk As Long, gSkip As Long, gFail As Long
Dim gTotalInst As Long, gTotalKeys As Long ' liste satiri / benzersiz dosya
Dim gOpened As Collection ' bizim actigimiz dosya yollari (son supurme icin)
Dim gNLeftOpen As Long ' kapanmadan kalan belge sayisi
Dim gFso As Object ' tek seferlik FileSystemObject
Dim gLogPath As String ' anlik iz surumu (cokus guvenli log yolu)

' Anlik iz: her satir hem hafizaya hem dosyaya yazilir (cokuste tani kaybolmaz).
Sub LogLine(msg As String)
    On Error Resume Next
    If Not gLog Is Nothing Then gLog.Add msg
    If gLogPath <> "" Then
        If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
        Dim ts As Object
        Set ts = gFso.OpenTextFile(gLogPath, 8, True)
        ts.WriteLine msg
        ts.Close
    End If
End Sub

Sub main()

    Set swApp = Application.SldWorks
    Set gLog = New Collection
    gOk = 0: gSkip = 0: gFail = 0: gTotalInst = 0: gTotalKeys = 0
    Set gOpened = New Collection: gNLeftOpen = 0
    Set gFso = CreateObject("Scripting.FileSystemObject")

    On Error GoTo catch_

    Dim listPath As String
    listPath = BASE_DIR & "\" & LIST_NAME
    If Not FileExists(listPath) Then
        Err.Raise vbError, "", "Liste bulunamadi: " & listPath
    End If

    ' Iz dosyasini BASLANGICTA ac
    On Error Resume Next
    gLogPath = BASE_DIR & "\export_raporu_step_liste.txt"
    Dim ts0 As Object
    Set ts0 = gFso.OpenTextFile(gLogPath, 8, True)
    ts0.WriteLine ""
    ts0.WriteLine "=== STEP LISTE v1-steplist BASLADI - " & Format(Now, "yyyy-MM-dd HH:mm:ss") & " ==="
    ts0.Close
    On Error GoTo catch_

    Dim lines As Collection
    Set lines = ReadListLines(listPath)
    gTotalKeys = lines.Count: gTotalInst = lines.Count

    If lines.Count = 0 Then
        swApp.SendMsgToUser2 "Listede islenecek satir yok: " & listPath, _
            swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
        GoTo finally_
    End If

    Dim i As Long: i = 0
    Dim it As Variant
    For Each it In lines
        i = i + 1
        LogLine "[DOSYA] " & CStr(it(0)) & " [" & CStr(it(1)) & "]"
        ProcessOneFile CStr(it(0)), CStr(it(1)), i, lines.Count
        If USE_BATCH_LIMIT And gNRun >= FILES_PER_RUN Then
            LogLine "[DURAKLATILDI] Bu kostuda " & gNRun & " dosya acildi, bellek sismeden duruldu. SW'yi KAPATIP tekrar calistirin, kaldigi yerden devam eder."
            Exit For
        End If
        If i Mod STATUS_EVERY = 0 Then
            DoEvents ' (2014'te status-bar API yok; sadece nefes aldir)
        End If
    Next it

    GoTo finally_

catch_:
    LogLine "[KRITIK] " & Err.Description
finally_:
    On Error Resume Next
    Call SweepOpenedDocs ' acik kalanlari kapat (dogrulamali)
    Call WriteLogFileList
    Dim msg As String
    msg = "Islem tamamlandi! (STEP liste modu)" & vbCrLf & vbCrLf & _
        "- Liste satiri: " & gTotalInst & vbCrLf & _
        "- Olusturulan STEP: " & gOk & vbCrLf & _
        "- Zaten mevcut (Atlandi): " & gSkip & vbCrLf & _
        "- Hatali: " & gFail & vbCrLf & _
        "- Kapanmadan kalan belge: " & gNLeftOpen
    If USE_BATCH_LIMIT And gNRun >= FILES_PER_RUN Then
        msg = msg & vbCrLf & vbCrLf & "DURAKLATILDI: bellek korumasi. SW'yi kapatip makroyu tekrar calistirin."
    End If
    If gFail > 0 Or gLog.Count > 0 Then
        msg = msg & vbCrLf & vbCrLf & "Detay: " & BASE_DIR & "\export_raporu_step_liste.txt"
    End If
    swApp.SendMsgToUser2 msg, swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
    Set gLog = Nothing

End Sub

' Liste dosyasini okur: her gecerli satir Array(tamDosyaYolu, config) olur.
' Bos satir + ' veya # ile baslayan satir atlanir. Uzantisiz ada .sldprt eklenir,
' yolsuz ada BASE_DIR eklenir.
Function ReadListLines(listPath As String) As Collection
    Set ReadListLines = New Collection
    On Error Resume Next
    Dim ts As Object
    Set ts = gFso.OpenTextFile(listPath, 1, False)
    If ts Is Nothing Then Exit Function
    Dim raw As String
    raw = ts.ReadAll()
    ts.Close
    Dim arr As Variant
    arr = Split(raw, vbCrLf)
    Dim i As Long
    For i = 0 To UBound(arr)
        Dim ln As String
        ln = Trim(CStr(arr(i)))
        If ln <> "" And Left(ln, 1) <> "'" And Left(ln, 1) <> "#" Then
            Dim f As String, c As String
            Dim p As Long
            p = InStr(ln, ",")
            If p > 0 Then
                f = Trim(Left(ln, p - 1))
                c = Trim(Mid(ln, p + 1))
            Else
                f = ln: c = ""
            End If
            If LCase(Right(f, 7)) <> ".sldprt" And LCase(Right(f, 7)) <> ".sldasm" Then
                Dim probe As String
                probe = f
                If InStr(f, "\") = 0 Then probe = BASE_DIR & "\" & f
                If gFso.FileExists(probe & ".sldasm") Then
                    f = f & ".sldasm" ' uzantisiz montaj adi
                Else
                    f = f & ".sldprt"
                End If
            End If
            If InStr(f, "\") = 0 Then f = BASE_DIR & "\" & f
            ReadListLines.Add Array(f, c)
        End If
    Next i
End Function

' --- Tek dosyayi gorunmez ac, STEP kaydet, kapat ---
Sub ProcessOneFile(partPath As String, conf As String, _
                   ByVal idx As Long, ByVal total As Long)

    On Error GoTo fail_

    LogLine "[BASLA] " & partPath & " (" & conf & ") [#" & idx & "/" & total & "]"
    Dim swPartModel As SldWorks.ModelDoc2
    Set swPartModel = Nothing

    Dim openedHere As Boolean
    openedHere = False

    ' Zaten acik mi? (kullanici onceden acmissa kapatma)
    On Error Resume Next
    Set swPartModel = swApp.GetOpenDocumentByName(partPath)
    On Error GoTo fail_

    If swPartModel Is Nothing Then
        Dim errVal As Long, warnVal As Long
        Dim docType As Long
        docType = swDocumentTypes_e.swDocPART
        If LCase(Right(partPath, 7)) = ".sldasm" Then docType = swDocumentTypes_e.swDocASSEMBLY
        On Error Resume Next
        swApp.DocumentVisible False, docType
        On Error GoTo fail_
        Set swPartModel = swApp.OpenDoc6(partPath, docType, _
            swOpenDocOptions_e.swOpenDocOptions_Silent Or swOpenDocOptions_e.swOpenDocOptions_ReadOnly, _
            conf, errVal, warnVal)
        On Error Resume Next
        swApp.DocumentVisible True, docType
        On Error GoTo fail_
        If Not swPartModel Is Nothing Then
            openedHere = True
            gOpened.Add partPath ' son supurme listesi
            gNRun = gNRun + 1 ' gercekten acilan her dosya sayilir
        End If
    End If

    ' Odunc belge (kullanici acmisti): giristeki kir bayragini sakla, cikista aynen iade et.
    Dim borrowedClean As Boolean: borrowedClean = False
    If False = openedHere Then
        On Error Resume Next
        If Not swPartModel Is Nothing Then borrowedClean = Not swPartModel.GetSaveFlag()
        On Error GoTo fail_
    End If

    If swPartModel Is Nothing Then
        gFail = gFail + 1
        LogLine "[ACILAMADI] " & partPath & " (" & conf & ") err=" & errVal
        Exit Sub
    End If

    ' Konfig DEGISTIRILMEZ, dosyanin aktif konfigi kullanilir.
    Dim effConf As String: effConf = ""
    Dim confSwitchedHere As Boolean: confSwitchedHere = False
    Dim origConf As String: origConf = ""
    On Error Resume Next
    origConf = swPartModel.ConfigurationManager.ActiveConfiguration.Name
    On Error GoTo fail_
    effConf = origConf

    Dim outFile As String
    Dim uretim As String
    uretim = SanitizeFolder(GetUretimSekli(swPartModel))
    outFile = BASE_DIR & "\" & STEP_SUBDIR & "\" & uretim & "\" & GetFileNameWithoutExtension(partPath) & ".step"

    If SKIP_EXISTING_FILES And FileExists(outFile) Then
        gSkip = gSkip + 1
        LogLine "[MEVCUT] " & outFile
    Else
        If ExportStepFile(swPartModel, outFile, openedHere) Then
            gOk = gOk + 1
            LogLine "[STEP-OK] " & outFile
        Else
            gFail = gFail + 1
            LogLine "[EXPORT-HATA] " & outFile
            On Error Resume Next
            Kill outFile ' yarim step birakma
            On Error GoTo fail_
        End If
    End If

    ' Odunc belgede biz kirlettiysen ve giriste temiz idiyse bayragi geri al (disk'e yazilmaz).
    If False = openedHere And borrowedClean Then
        On Error Resume Next
        If Not swPartModel Is Nothing Then ClearDirtyFlag swPartModel
        On Error GoTo fail_
    End If

    If openedHere Then
        On Error Resume Next
        If Not swPartModel Is Nothing Then ClearDirtyFlag swPartModel
        If Not swPartModel Is Nothing Then Call CloseDocVerified(partPath, swPartModel.GetTitle())
        On Error GoTo fail_
    End If

    On Error Resume Next
    swApp.DocumentVisible True, docType
    Set swPartModel = Nothing
    Exit Sub

fail_:
    gFail = gFail + 1
    LogLine "[HATA] " & partPath & " (" & conf & "): " & Err.Description
    On Error Resume Next
    If False = openedHere And borrowedClean Then
        If Not swPartModel Is Nothing Then ClearDirtyFlag swPartModel
    End If
    If openedHere Then
        If Not swPartModel Is Nothing Then ClearDirtyFlag swPartModel
        If Not swPartModel Is Nothing Then Call CloseDocVerified(partPath, swPartModel.GetTitle())
    End If
    swApp.DocumentVisible True, docType
    Set swPartModel = Nothing

End Sub

' STEP kaydet: SaveAs (2014 imzasi: SaveAs(path, version, options, exportData, errors, warnings)).
Function ExportStepFile(partModel As SldWorks.ModelDoc2, outFilePath As String, _
                        ByVal openedHere As Boolean) As Boolean

    ExportStepFile = False

    Dim swModel As SldWorks.ModelDoc2
    Set swModel = partModel

    Dim wasHidden As Boolean: wasHidden = False

    On Error GoTo fail_

    If False = swModel.Visible Then
        wasHidden = True
        swModel.Visible = True
    End If

    swApp.ActivateDoc3 swModel.GetPathName(), False, _
        swRebuildOnActivation_e.swDontRebuildActiveDoc, 0

    CreateDirectories Left(outFilePath, InStrRev(outFilePath, "\"))

    Dim errVal As Long, warnVal As Long
    If False <> swModel.Extension.SaveAs(outFilePath, swSaveAsCurrentVersion, _
            swSaveAsOptions_Silent, Nothing, errVal, warnVal) Then
        If FileExists(outFilePath) Then ExportStepFile = True
    End If

    GoTo cleanup_

fail_:
    ExportStepFile = False
    On Error Resume Next
    LogLine "[EXPORT-EXC] " & outFilePath & ": " & Err.Description

cleanup_:
    On Error Resume Next
    ' Sadece odunc aldigimiz (zaten acik olan) dokumanin gorunurlugunu geri al
    If wasHidden And False = openedHere Then
        swModel.Visible = False
    End If
    Set swModel = Nothing

End Function

' --- Dosya / path yardimcilari ---

' uretim_sekli custom property'sini once aktif konfigden, olmazsa dosya
' ozelliklerinden okur. Bulunamazsa bos doner (klasor Diger olur).
Function GetUretimSekli(model As SldWorks.ModelDoc2) As String
    On Error Resume Next
    GetUretimSekli = ""
    Dim cfg As String: cfg = ""
    cfg = model.ConfigurationManager.ActiveConfiguration.Name
    Dim v As String: v = ""
    v = model.Extension.CustomPropertyManager(cfg).Get("uretim_sekli")
    If Trim(v) = "" Then
        v = ""
        v = model.Extension.CustomPropertyManager("").Get("uretim_sekli")
    End If
    GetUretimSekli = Trim(v)
End Function

' Klasor adi icin yasak karakterleri temizler, bos ise Diger verir.
Function SanitizeFolder(s As String) As String
    On Error Resume Next
    Dim bad As Variant
    bad = Array("\", "/", ":", "*", "?", """", "<", ">", "|")
    Dim b As Variant
    For Each b In bad
        s = Replace(s, CStr(b), "_")
    Next b
    s = Trim(s)
    If s = "" Then s = "Diger"
    SanitizeFolder = s
End Function

Function GetFileNameWithoutExtension(path As String) As String
    Dim s As Long, e As Long
    s = InStrRev(path, "\") + 1
    e = InStrRev(path, ".")
    If e <= s Then
        GetFileNameWithoutExtension = Mid(path, s)
    Else
        GetFileNameWithoutExtension = Mid(path, s, e - s)
    End If
End Function

Function FileExists(filePath As String) As Boolean
    On Error Resume Next
    If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
    FileExists = gFso.FileExists(filePath)
End Function

' Kir-bayragi temizleme: SetSaveFlag imzasi 2014'te farkli -> gec baglama kullan.
Sub ClearDirtyFlag(model As SldWorks.ModelDoc2)
    On Error Resume Next
    Call CallByName(model, "SetSaveFlag", VbMethod, False)
    If Err.Number <> 0 Then
        Err.Clear
        CallByName model, "SetSaveFlag", VbLet, False ' olur da property ise
    End If
End Sub

Sub CreateDirectories(path As String)
    If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
    If gFso.FolderExists(path) Then Exit Sub
    CreateDirectories gFso.GetParentFolderName(path)
    gFso.CreateFolder path
End Sub

' Bizim actigimiz belgeleri tek tek kapat, kapanmayani say + logla.
Sub CloseDocVerified(docPath As String, docTitle As String)
    On Error Resume Next
    If Right(docTitle, 2) = " *" Then docTitle = Left(docTitle, Len(docTitle) - 2) ' kirli baslik yildizi (2014)
    swApp.CloseDoc docTitle ' statement olarak cagir: donus degeri surume gore degisir, dogrulama yeterli
    Dim still As Object
    Set still = swApp.GetOpenDocumentByName(docPath)
    If Not still Is Nothing Then
        gNLeftOpen = gNLeftOpen + 1
        LogLine "[KAPAT-HATA] " & docPath
    End If
End Sub

' Kosu sonunda acik kalmis kendi belgelerimizi supur.
Sub SweepOpenedDocs()
    On Error Resume Next
    If gOpened Is Nothing Then Exit Sub
    Dim sp As Variant
    For Each sp In gOpened
        Dim od As Object
        Set od = swApp.GetOpenDocumentByName(CStr(sp))
        If Not od Is Nothing Then
            Dim ot As String: ot = ""
            ot = od.GetTitle()
            If ot <> "" Then Call CloseDocVerified(CStr(sp), ot)
        End If
    Next sp
End Sub

Sub WriteLogFileList()
    On Error Resume Next
    If gLog Is Nothing Then Exit Sub
    If gLog.Count = 0 And gFail = 0 Then Exit Sub
    If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
    Dim ts As Object
    Set ts = gFso.OpenTextFile(BASE_DIR & "\export_raporu_step_liste.txt", 8, True)
    ts.WriteLine ""
    ts.WriteLine "========================================================"
    ts.WriteLine "STEP LISTE RAPORU v1-steplist - " & Format(Now, "yyyy-MM-dd HH:mm:ss")
    ts.WriteLine "Satir: " & gTotalInst & " | OK: " & gOk & " | Mevcut-Atla: " & gSkip & " | Hata: " & gFail
    ts.WriteLine "========================================================"
    Dim j As Long
    For j = 1 To gLog.Count
        ts.WriteLine gLog(j)
    Next j
    ts.WriteLine ""
    ts.Close
End Sub

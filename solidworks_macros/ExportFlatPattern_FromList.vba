' =========================================================================
' DXF FLAT-PATTERN + BEND PDF EXPORT - LISTE MODU v4-list (SolidWorks 2014 uyumlu)
' Turedi: ExportFlatPattern_CrashSafe (v15 motoru aynen korunur).
' Fark: montaj taramasi YOK, vida acip kapatma YOK. Kullanici sac_liste.txt verir.
' Liste formati (her satir): KOD veya KOD,ADET
'   - LN kodlari: DXF alinir. Ornek: M3E2LN04,12 -> ...\M3E2LN04_12_Adet.dxf
'     (malzeme/kalinlik klasor yapisi korunur, adete gore dosya adi degisir).
'   - BN kodlari (bukum): DXF YOK, KOD.slddrw teknik resmi PDF'e cevrilir ->
'     Bending\<KOD>.pdf (duz klasor, adet dosya adina girmez).
'   - Konfigurasyon DEGISTIRILMEZ; dosya hangi aktif konfigle acilirsa islem ondan yapilir.
' Turlar: FILES_PER_RUN=50'de guvenli durur, SKIP_EXISTING ile kaldigi yerden devam.
' Kullanim: liste dosyasini BASE_DIR'e sac_liste.txt olarak kaydet, makroyu calistir
' (acik montaja gerek YOK).
' =========================================================================
Option Explicit

Enum SheetMetalOptions_e
    ExportFlatPatternGeometry = 1
    IncludeHiddenEdges = 2
    ExportBendLines = 4
    IncludeSketches = 8
    MergeCoplanarFaces = 16
    ExportLibraryFeatures = 32
    ExportFormingTools = 64
End Enum

' --- AYARLAR ---
Const BASE_DIR As String = "D:\Ortak Drive'lar\Matia Mobility\2000_TECHNICAL\2300_3D_CAD\2310_TekRMD_Sldwrks"
Const LIST_NAME As String = "sac_liste.txt"
Const SKIP_EXISTING_FILES As Boolean = True
Const OUT_NAME_TEMPLATE As String = "Lazer_Kesim&Bukum\DXFs\<$PRP:Malzeme>\<$CLPRP:Sac Levha Kalınlığı>\<_FileName_>.dxf"
Const FLAT_PATTERN_OPTIONS As Long = SheetMetalOptions_e.ExportFlatPatternGeometry
Const STATUS_EVERY As Long = 5   ' her N parcada DoEvents (nefes)
Const FILES_PER_RUN As Long = 50 ' USE_BATCH_LIMIT kapaliyken kullanilmaz (yedekte durur)
Dim gNRun As Long ' bu kostuda acilan dosya sayaci
Const ALLOW_CUTLIST_UPDATE As Boolean = True ' v4-list: ACIK (tek dosya acik, rebuild yalitilmis)
Const USE_BATCH_LIMIT As Boolean = False ' False = tur siniri YOK, liste sonuna kadar gider (kullanici istegi)

Dim swApp As SldWorks.SldWorks
Dim gLog As Collection
Dim gOk As Long, gSkip As Long, gFail As Long, gNotSheet As Long, gPdf As Long
Dim gDiagDone As Boolean ' ilk atlanan parcanin tani dokumu bir kez yapilir
Dim gTotalInst As Long, gTotalKeys As Long ' liste satiri / benzersiz dosya
Dim gOpened As Collection ' bizim actigimiz dosya yollari (son supurme icin)
Dim gNLeftOpen As Long ' kapanmadan kalan belge sayisi
Dim gRe As Object, gFso As Object ' tek seferlik COM nesneleri (RegExp + FileSystemObject)
Dim gLogPath As String ' anlik iz surumu (cokus guvenli log yolu)
Dim gOutRoot As String ' orn. Lazer_Kesim&Bukum_13102026 (kosu tarihli kok klasor)

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
    gOk = 0: gSkip = 0: gFail = 0: gNotSheet = 0: gPdf = 0: gDiagDone = False: gTotalInst = 0: gTotalKeys = 0
    Set gOpened = New Collection: gNLeftOpen = 0
    Set gRe = CreateObject("VBScript.RegExp")
    gRe.Global = True: gRe.IgnoreCase = True: gRe.Pattern = "<[^>]*>"
    Set gFso = CreateObject("Scripting.FileSystemObject")
    gOutRoot = "Lazer_Kesim&Bukum_" & Format(Date, "ddmmyyyy") ' orn. ..._13102026

    On Error GoTo catch_

    Dim listPath As String
    listPath = BASE_DIR & "\" & LIST_NAME
    If Not FileExists(listPath) Then
        Err.Raise vbError, "", "Liste bulunamadi: " & listPath & vbCrLf & _
            "Her satira KOD veya KOD,ADET yazin (ornek: M3E2LN04,12)."
    End If

    ' Iz dosyasini BASLANGICTA ac
    On Error Resume Next
    gLogPath = BASE_DIR & "\export_raporu_liste.txt"
    Dim ts0 As Object
    Set ts0 = gFso.OpenTextFile(gLogPath, 8, True)
    ts0.WriteLine ""
    ts0.WriteLine "=== DXF LISTE v4-list BASLADI - " & Format(Now, "yyyy-MM-dd HH:mm:ss") & " ==="
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
        LogLine "[DOSYA] " & CStr(it(0)) & " [adet:" & CStr(it(1)) & "]"
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
    msg = "Islem tamamlandi! (liste modu)" & vbCrLf & vbCrLf & _
        "- Liste satiri: " & gTotalInst & vbCrLf & _
        "- Olusturulan DXF: " & gOk & vbCrLf & _
        "- Olusturulan PDF (Bending): " & gPdf & vbCrLf & _
        "- Zaten mevcut (Atlandi): " & gSkip & vbCrLf & _
        "- Sac degil (Atlandi): " & gNotSheet & vbCrLf & _
        "- Hatali: " & gFail & vbCrLf & _
        "- Kapanmadan kalan belge: " & gNLeftOpen
    If USE_BATCH_LIMIT And gNRun >= FILES_PER_RUN Then
        msg = msg & vbCrLf & vbCrLf & "DURAKLATILDI: bellek korumasi. SW'yi kapatip makroyu tekrar calistirin."
    End If
    If gFail > 0 Or gLog.Count > 0 Then
        msg = msg & vbCrLf & vbCrLf & "Detay: " & BASE_DIR & "\export_raporu_liste.txt"
    End If
    swApp.SendMsgToUser2 msg, swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
    Set gLog = Nothing

End Sub

' Liste dosyasini okur: her gecerli satir Array(tamDosyaYolu, adet) olur.
' Format: KOD veya KOD,ADET (2. sutun artik konfig DEGIL, dosya adina giren adettir).
' Bos satir + ' veya # ile baslayan satir atlanir. Uzantisiz ada .sldprt eklenir,
' yolsuz ada BASE_DIR eklenir. BN satirlari adetsiz de olabilir (adet PDF'de kullanilmaz).
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
            If LCase(Right(f, 7)) <> ".sldprt" Then f = f & ".sldprt"
            If InStr(f, "\") = 0 Then f = BASE_DIR & "\" & f
            ReadListLines.Add Array(f, c)
        End If
    Next i
End Function

' --- FAZ 2: tek dosyayi gorunmez ac, isle, kapat ---
Sub ProcessOneFile(partPath As String, qty As String, _
                   ByVal idx As Long, ByVal total As Long)

    On Error GoTo fail_

    LogLine "[BASLA] " & partPath & " [adet:" & qty & "] [#" & idx & "/" & total & "]"

    ' BN (bukum) kodu: DXF degil, teknik resimden PDF (Bending klasoru, adet yok).
    If InStr(UCase(GetFileNameWithoutExtension(partPath)), "BN") > 0 Then
        ProcessBendPdf partPath, GetFileNameWithoutExtension(partPath), idx, total
        Exit Sub
    End If

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
        On Error Resume Next
        swApp.DocumentVisible False, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        Set swPartModel = swApp.OpenDoc6(partPath, swDocumentTypes_e.swDocPART, _
            swOpenDocOptions_e.swOpenDocOptions_Silent Or swOpenDocOptions_e.swOpenDocOptions_ReadOnly, _
            "", errVal, warnVal)
        On Error Resume Next
        swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
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
        LogLine "[ACILAMADI] " & partPath & " [adet:" & qty & "] err=" & errVal
        Exit Sub
    End If

    ' Liste modu: konfig DEGISTIRILMEZ, dosyanin aktif konfigi kullanilir.
    Dim effConf As String: effConf = ""
    Dim confSwitchedHere As Boolean: confSwitchedHere = False
    Dim origConf As String: origConf = ""
    On Error Resume Next
    origConf = swPartModel.ConfigurationManager.ActiveConfiguration.Name
    On Error GoTo fail_
    effConf = origConf

    ' Aynali dosya (ozel flat-turev konfigli): turev konfigden tek flat (testli yontem).
    ' Normal dosyalar bu dala girmez, eski yol aynen calisir.
    Dim mirrorDone As Boolean: mirrorDone = False
    If HasCustomFlatConfig(swPartModel) Then
        mirrorDone = ExportMirrorSingle(swPartModel, partPath, qty, origConf, openedHere)
    End If
    If False = mirrorDone Then
        ProcessSheetMetalModel swPartModel, swPartModel, effConf, openedHere, qty
    End If

    ' Konfig degistirdiysek geri al (odunc belgede sart, kendi actigimizda zararsiz).
    If confSwitchedHere And origConf <> "" Then
        On Error Resume Next
        swPartModel.ShowConfiguration2 origConf
        On Error GoTo fail_
    End If

    ' Odunc belgede biz kirlettiysen ve giriste temiz idiyse bayragi geri al (disk'e yazilmaz).
    If False = openedHere And borrowedClean Then
        ClearDirtyFlag swPartModel ' gec baglama (2014 imza farki derleme patlatiyordu)
    End If

    If openedHere Then
        On Error Resume Next
        ClearDirtyFlag swPartModel ' disk'e yazmadan kir bayragini temizle -> CloseDoc takilmaz
        Call CloseDocVerified(partPath, swPartModel.GetTitle())
        On Error GoTo fail_
    End If
    Set swPartModel = Nothing
    Exit Sub

fail_:
    gFail = gFail + 1
    LogLine "[HATA] " & partPath & " [adet:" & qty & "]: " & Err.Description
    On Error Resume Next
    If confSwitchedHere And origConf <> "" Then
        If Not swPartModel Is Nothing Then swPartModel.ShowConfiguration2 origConf
    End If
    If False = openedHere And borrowedClean Then
        If Not swPartModel Is Nothing Then ClearDirtyFlag swPartModel
    End If
    If openedHere Then
        If Not swPartModel Is Nothing Then ClearDirtyFlag swPartModel
        If Not swPartModel Is Nothing Then Call CloseDocVerified(partPath, swPartModel.GetTitle())
    End If
    swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
    Set swPartModel = Nothing

End Sub

' --- Aynali/cok konfigli dosya destegi (testli: MirrorTest 3/3 duz geldi) ---
' Ozel flat-turev konfigi var mi? ("LeftSM-FLAT-PATTERN" gibi; SW otomatik
' "SM-FLAT-PATTERN" sayilmaz -> normal dosyalar bu dala girmez.)
Function HasCustomFlatConfig(model As SldWorks.ModelDoc2) As Boolean
    HasCustomFlatConfig = False
    On Error Resume Next
    Dim v As Variant
    v = model.GetConfigurationNames
    If IsEmpty(v) Then Exit Function
    Dim i As Long
    For i = 0 To UBound(v)
        Dim nm As String
        nm = UCase(Trim(CStr(v(i))))
        If nm <> "SM-FLAT-PATTERN" And InStr(nm, "FLAT-PATTERN") > 0 Then
            HasCustomFlatConfig = True
            Exit Function
        End If
    Next i
End Function

' Cok konfigli dosyada konfigleri sirayla dener, ilk basarili flat'i ayni
' sablon adiyla tek DXF'e yazar (SKIP'e bakmaz, taze yazar).
' Kendi actigimiz belgede geri-donus switch'i YOK (kapatilacak; testteki son
' crash suphelisi). Odunc belgede konfig + gorunurluk iade edilir.
Function ExportMirrorSingle(swModel As SldWorks.ModelDoc2, partPath As String, _
                            qty As String, origConf As String, _
                            ByVal openedHere As Boolean) As Boolean
    ExportMirrorSingle = False
    On Error GoTo fail_
    Dim wasHidden As Boolean: wasHidden = False
    On Error Resume Next
    If False = swModel.Visible Then
        wasHidden = True
        swModel.Visible = True
    End If
    swApp.ActivateDoc3 swModel.GetPathName(), False, _
        swRebuildOnActivation_e.swDontRebuildActiveDoc, 0
    On Error GoTo fail_
    Dim vConfs As Variant
    vConfs = swModel.GetConfigurationNames
    If IsEmpty(vConfs) Then GoTo cleanup_
    Dim swPart As SldWorks.PartDoc
    Set swPart = swModel
    Dim ci As Long
    For ci = 0 To UBound(vConfs)
        If MirrorExportConfig(swModel, swPart, CStr(vConfs(ci)), qty) Then
            LogLine "[TEK-FLAT] " & GetFileNameWithoutExtension(partPath) & " <- " & CStr(vConfs(ci))
            ExportMirrorSingle = True
            Exit For
        End If
    Next ci
    If False = ExportMirrorSingle Then
        LogLine "[MIRROR-BASARISIZ] " & partPath & " (normal yola dusuldu)"
    End If
    GoTo cleanup_
fail_:
    LogLine "[HATA-mirror] " & partPath & ": " & Err.Description
    On Error Resume Next
cleanup_:
    On Error Resume Next
    If False = openedHere Then
        If origConf <> "" Then swModel.ShowConfiguration2 origConf
        If wasHidden Then swModel.Visible = False
    End If
    Set swPart = Nothing
End Function

' Tek konfigde ilk secilebilir flat'i yazar; aktif konfig no-op'u zararsizca gecilir.
Function MirrorExportConfig(swModel As SldWorks.ModelDoc2, swPart As SldWorks.PartDoc, _
                           confName As String, qty As String) As Boolean
    MirrorExportConfig = False
    On Error GoTo fail_
    If False = swModel.ShowConfiguration2(confName) Then
        LogLine "[CONF-GEC] " & confName & " (aktifle ayni olabilir, sonraki)"
        Exit Function
    End If
    Dim vFlats As Variant
    vFlats = GetFlatPatternFeatures(swModel)
    If IsEmpty(vFlats) Then Exit Function
    Dim vCuts As Variant
    vCuts = GetCutListFeatures(swModel)
    If IsEmpty(vCuts) Then Exit Function
    Dim fi As Long
    For fi = 0 To UBound(vFlats)
        Dim swF As SldWorks.Feature
        Set swF = vFlats(fi)
        If False = swF.Select2(False, -1) Then
            LogLine "[ATLA-suppressed] " & confName & " flat=" & swF.Name
        Else
            Dim swC As SldWorks.Feature
            Set swC = FindCutListForFlat(swModel, vCuts, swF)
            If swC Is Nothing Then Set swC = vCuts(0)
            Dim outFile As String
            outFile = ComposeOutFileName(DatedTemplate(), swModel, swModel, confName, swF, swC)
            outFile = InsertQtySuffix(outFile, qty)
            If FileExists(outFile) Then LogLine "[MIRROR-YENIDEN] " & outFile
            If ExportFlatPattern(swPart, swF, outFile, FLAT_PATTERN_OPTIONS, confName, True) Then
                gOk = gOk + 1
                LogLine "[DXF-OK] " & outFile
                MirrorExportConfig = True
                Set swF = Nothing
                Exit Function
            Else
                gFail = gFail + 1
                LogLine "[EXPORT-HATA] " & outFile
                On Error Resume Next
                Kill outFile
                On Error GoTo fail_
            End If
        End If
        Set swF = Nothing
    Next fi
    Exit Function
fail_:
    MirrorExportConfig = False
    On Error Resume Next
    LogLine "[HATA-mirror-conf] " & confName & ": " & Err.Description
End Function

' BN (bukum) islemi: KOD.slddrw teknik resmini gorunmez acip Bending\<KOD>.pdf yapar.
' Adet PDF adina girmez. Kendi actigini dogrulamali kapatir.
Sub ProcessBendPdf(partPath As String, baseName As String, _
                   ByVal idx As Long, ByVal total As Long)
    On Error GoTo fail_

    Dim dwgPath As String
    dwgPath = Left(partPath, InStrRev(partPath, ".") - 1) & ".slddrw"

    If Not FileExists(dwgPath) Then
        gFail = gFail + 1
        LogLine "[RESIM-YOK] " & dwgPath & " [#" & idx & "/" & total & "]"
        Exit Sub
    End If

    Dim outPdf As String
    outPdf = BASE_DIR & "\" & gOutRoot & "\PDFs\" & baseName & ".pdf"

    If SKIP_EXISTING_FILES And FileExists(outPdf) Then
        gSkip = gSkip + 1
        LogLine "[MEVCUT] " & outPdf
        Exit Sub
    End If

    CreateDirectories BASE_DIR & "\" & gOutRoot & "\PDFs"

    Dim swDwg As SldWorks.ModelDoc2
    Set swDwg = Nothing
    Dim openedHere As Boolean: openedHere = False

    On Error Resume Next
    Set swDwg = swApp.GetOpenDocumentByName(dwgPath)
    On Error GoTo fail_

    Dim errVal As Long, warnVal As Long
    If swDwg Is Nothing Then
        On Error Resume Next
        swApp.DocumentVisible False, swDocumentTypes_e.swDocDRAWING
        On Error GoTo fail_
        Set swDwg = swApp.OpenDoc6(dwgPath, swDocumentTypes_e.swDocDRAWING, _
            swOpenDocOptions_e.swOpenDocOptions_Silent Or swOpenDocOptions_e.swOpenDocOptions_ReadOnly, _
            "", errVal, warnVal)
        On Error Resume Next
        swApp.DocumentVisible True, swDocumentTypes_e.swDocDRAWING
        On Error GoTo fail_
        If Not swDwg Is Nothing Then
            openedHere = True
            gOpened.Add dwgPath
            gNRun = gNRun + 1
        End If
    End If

    If swDwg Is Nothing Then
        gFail = gFail + 1
        LogLine "[ACILAMADI] " & dwgPath & " err=" & errVal
        Exit Sub
    End If

    ' Gorunmez + aktive edilmemis resimde SaveAs2 PDF uretmiyor -> gorunur + aktive et.
    Dim dwgWasHidden As Boolean: dwgWasHidden = False
    On Error Resume Next
    If False = swDwg.Visible Then
        dwgWasHidden = True
        swDwg.Visible = True
    End If
    swApp.ActivateDoc3 dwgPath, False, _
        swRebuildOnActivation_e.swDontRebuildActiveDoc, 0
    On Error GoTo fail_

    Dim ok As Boolean: ok = False
    Dim pdfErr As Long, pdfWarn As Long
    pdfErr = 0: pdfWarn = 0
    On Error Resume Next
    ok = swDwg.Extension.SaveAs(outPdf, swSaveAsVersion_e.swSaveAsCurrentVersion, _
        swSaveAsOptions_e.swSaveAsOptions_Silent, Nothing, pdfErr, pdfWarn)
    On Error GoTo fail_
    LogLine "[PDF-SAVE] " & baseName & " ok=" & ok & " err=" & pdfErr & " warn=" & pdfWarn

    If ok And FileExists(outPdf) Then
        gPdf = gPdf + 1
        LogLine "[PDF-OK] " & outPdf
    Else
        gFail = gFail + 1
        LogLine "[PDF-HATA] " & outPdf
        On Error Resume Next
        Kill outPdf
        On Error GoTo fail_
    End If

    If openedHere Then
        On Error Resume Next
        ClearDirtyFlag swDwg
        Call CloseDocVerified(dwgPath, swDwg.GetTitle())
        On Error GoTo fail_
    End If
    If False = openedHere And dwgWasHidden Then swDwg.Visible = False
    Set swDwg = Nothing
    Exit Sub

fail_:
    gFail = gFail + 1
    LogLine "[HATA] " & dwgPath & ": " & Err.Description
    On Error Resume Next
    If openedHere Then
        If Not swDwg Is Nothing Then ClearDirtyFlag swDwg
        If Not swDwg Is Nothing Then Call CloseDocVerified(dwgPath, swDwg.GetTitle())
    End If
    swApp.DocumentVisible True, swDocumentTypes_e.swDocDRAWING
    Set swDwg = Nothing
End Sub

' DXF adina adet ekler: ...\M3E2LN04.dxf + "12" -> ...\M3E2LN04_12_Adet.dxf
Function InsertQtySuffix(outFile As String, qty As String) As String
    InsertQtySuffix = outFile
    qty = Trim(qty)
    If qty = "" Then Exit Function
    Dim p As Long
    p = InStrRev(outFile, ".")
    If p = 0 Then p = Len(outFile) + 1
    InsertQtySuffix = Left(outFile, p - 1) & "_" & ReplaceInvalidPathSymbols(qty) & "_Adet" & Mid(outFile, p)
End Function

' Ilk atlanan parcanin unsur tip adlarini loga doker ("neden sac degil?" sorusunun cevabi).
Sub LogFirstSkipDiag(partModel As SldWorks.ModelDoc2)
    If gDiagDone Then Exit Sub
    gDiagDone = True
    On Error Resume Next
    Dim names As String: names = ""
    Dim n As Long: n = 0
    Dim swF As SldWorks.Feature
    Set swF = partModel.FirstFeature()
    Do While Not swF Is Nothing And n < 60
        names = names & swF.GetTypeName2() & ";"
        n = n + 1
        Set swF = swF.GetNextFeature()
    Loop
    Dim nSM As Long: nSM = 0
    Dim vSM As Variant
    vSM = GetFeaturesByType(partModel, "SheetMetal")
    If Not IsEmpty(vSM) Then nSM = UBound(vSM) + 1
    LogLine "TANI: " & GetFileNameWithoutExtension(partModel.GetPathName()) & _
        " | UnsurSayisi=" & n & " | SheetMetalAdedi=" & nSM & " | Tipler=[" & names & "]"
End Sub

' Parcadaki SheetMetal unsuru adedi (hizli tani icin; hata verirse 0 doner)
Function CountSheetMetalFeats(partModel As SldWorks.ModelDoc2) As Long
    CountSheetMetalFeats = 0
    On Error Resume Next
    Dim vSM As Variant
    vSM = GetFeaturesByType(partModel, "SheetMetal")
    If Not IsEmpty(vSM) Then CountSheetMetalFeats = UBound(vSM) + 1
End Function

Sub ProcessSheetMetalModel(rootModel As SldWorks.ModelDoc2, sheetMetalModel As SldWorks.ModelDoc2, _
                           conf As String, ByVal openedHere As Boolean, qty As String)

    On Error GoTo fail_

    ' Hizli sac kontrolu: FlatPattern yoksa sessizce gec (sac degil, hata degil)
    Dim vFlatPatternFeats As Variant
    vFlatPatternFeats = GetFlatPatternFeatures(sheetMetalModel)

    If IsEmpty(vFlatPatternFeats) Then
        gNotSheet = gNotSheet + 1
        Call LogFirstSkipDiag(sheetMetalModel)
        LogLine "[SAC-DEGIL] " & GetFileNameWithoutExtension(sheetMetalModel.GetPathName()) & _
            " (" & conf & ") | SheetMetalAdedi=" & CountSheetMetalFeats(sheetMetalModel)
        Exit Sub
    End If

    Dim vCutListFeats As Variant
    vCutListFeats = GetCutListFeatures(sheetMetalModel)

    If IsEmpty(vCutListFeats) Then
        gFail = gFail + 1
        LogLine "[CUTLIST-YOK] " & GetFileNameWithoutExtension(sheetMetalModel.GetPathName()) & " (" & conf & ")"
        Exit Sub
    End If

    Dim swProcessed() As SldWorks.Feature
    Dim hasProc As Boolean: hasProc = False

    Dim i As Long
    For i = 0 To UBound(vFlatPatternFeats)

        Dim swFlatFeat As SldWorks.Feature
        Set swFlatFeat = vFlatPatternFeats(i)

        Dim swCutFeat As SldWorks.Feature
        Set swCutFeat = FindCutListForFlat(sheetMetalModel, vCutListFeats, swFlatFeat)

        If swCutFeat Is Nothing Then
            ' cut-list eslesmezse ilk cut-list'i kullan (cok govdeli dosyalarda devam et)
            Set swCutFeat = vCutListFeats(0)
        End If

        Dim k As Long, dup As Boolean: dup = False
        If hasProc Then
            For k = 0 To UBound(swProcessed)
                If swApp.IsSame(swProcessed(k), swCutFeat) = swObjectEquality.swObjectSame Then
                    dup = True: Exit For
                End If
            Next k
        End If

        If Not dup Then
            If Not hasProc Then
                ReDim swProcessed(0): hasProc = True
            Else
                ReDim Preserve swProcessed(UBound(swProcessed) + 1)
            End If
            Set swProcessed(UBound(swProcessed)) = swCutFeat

            Dim outFile As String
            outFile = ComposeOutFileName(DatedTemplate(), rootModel, sheetMetalModel, conf, swFlatFeat, swCutFeat)
            outFile = InsertQtySuffix(outFile, qty) ' M3E2LN04,12 -> M3E2LN04_12_Adet.dxf

            If SKIP_EXISTING_FILES And FileExists(outFile) Then
                gSkip = gSkip + 1
                LogLine "[MEVCUT] " & outFile
            Else
                If ExportFlatPattern(sheetMetalModel, swFlatFeat, outFile, FLAT_PATTERN_OPTIONS, conf, openedHere) Then
                    gOk = gOk + 1
                    LogLine "[DXF-OK] " & outFile
                Else
                    gFail = gFail + 1
                    LogLine "[EXPORT-HATA] " & outFile
                    On Error Resume Next
                    Kill outFile ' yarim dxf birakma
                    On Error GoTo fail_
                End If
            End If
        End If
        Set swFlatFeat = Nothing
        Set swCutFeat = Nothing
    Next i
    Exit Sub

fail_:
    gFail = gFail + 1
    LogLine "[HATA] " & sheetMetalModel.GetPathName() & " (" & conf & "): " & Err.Description

End Sub

' FlatPattern'in govdesini bul, hangi cut-list klasorundeyse onu don
Function FindCutListForFlat(model As SldWorks.ModelDoc2, vCutListFeats As Variant, _
                            flatFeat As SldWorks.Feature) As SldWorks.Feature

    On Error Resume Next
    Set FindCutListForFlat = Nothing

    ' Tek cut-list varsa govde eslestirmeye girme: govde yuklemeden ilk klasoru kullan.
    If UBound(vCutListFeats) = 0 Then
        Set FindCutListForFlat = vCutListFeats(0)
        Exit Function
    End If

    Dim swFP As SldWorks.FlatPatternFeatureData
    Set swFP = flatFeat.GetDefinition()
    If swFP Is Nothing Then Exit Function

    Dim swEnt As SldWorks.Entity
    Set swEnt = swFP.FixedFace2
    If swEnt Is Nothing Then Exit Function

    Dim swBody As SldWorks.Body2
    If TypeOf swEnt Is SldWorks.Face2 Then
        Dim f As SldWorks.Face2: Set f = swEnt
        Set swBody = f.GetBody()
    ElseIf TypeOf swEnt Is SldWorks.Edge Then
        Dim e As SldWorks.Edge: Set e = swEnt
        Set swBody = e.GetBody()
    ElseIf TypeOf swEnt Is SldWorks.Vertex Then
        Dim v As SldWorks.Vertex: Set v = swEnt
        Set swBody = v.GetBody()
    End If
    If swBody Is Nothing Then Exit Function

    Dim i As Long
    For i = 0 To UBound(vCutListFeats)
        Dim swBF As SldWorks.BodyFolder
        Set swBF = vCutListFeats(i).GetSpecificFeature2()
        If Not swBF Is Nothing Then
            Dim vB As Variant
            vB = swBF.GetBodies()
            If Not IsEmpty(vB) Then
                Dim j As Long
                For j = 0 To UBound(vB)
                    If swApp.IsSame(vB(j), swBody) = swObjectEquality.swObjectSame Then
                        Set FindCutListForFlat = vCutListFeats(i)
                        Exit Function
                    End If
                Next j
            End If
        End If
    Next i

End Function

Function GetCutListFeatures(model As SldWorks.ModelDoc2) As Variant
    GetCutListFeatures = GetFeaturesByType(model, "CutListFolder")
End Function

Function GetFlatPatternFeatures(model As SldWorks.ModelDoc2) As Variant
    GetFlatPatternFeatures = GetFeaturesByType(model, "FlatPattern")
End Function

Function GetFeaturesByType(model As SldWorks.ModelDoc2, typeName As String) As Variant

    Dim swFeats() As SldWorks.Feature
    Dim hasAny As Boolean: hasAny = False

    Dim swFeat As SldWorks.Feature
    Set swFeat = model.FirstFeature()

    Do While Not swFeat Is Nothing
        If ALLOW_CUTLIST_UPDATE Then
            If typeName = "CutListFolder" And swFeat.GetTypeName2() = "SolidBodyFolder" Then
                Dim swBF0 As SldWorks.BodyFolder
                Set swBF0 = swFeat.GetSpecificFeature2()
                If Not swBF0 Is Nothing Then
                    Call swBF0.UpdateCutList()
                End If
            End If
        End If
        CollectFeature swFeat, swFeats, hasAny, typeName
        Set swFeat = swFeat.GetNextFeature()
    Loop

    If Not hasAny Then
        GetFeaturesByType = Empty
    Else
        GetFeaturesByType = swFeats
    End If

End Function

Sub CollectFeature(thisFeat As SldWorks.Feature, featsArr() As SldWorks.Feature, _
                   ByRef hasAny As Boolean, typeName As String)

    If thisFeat.GetTypeName2() = typeName Then
        If Not hasAny Then
            ReDim featsArr(0)
            Set featsArr(0) = thisFeat
            hasAny = True
        Else
            Dim i As Long, found As Boolean: found = False
            For i = 0 To UBound(featsArr)
                If swApp.IsSame(featsArr(i), thisFeat) = swObjectEquality.swObjectSame Then
                    found = True: Exit For
                End If
            Next i
            If Not found Then
                ReDim Preserve featsArr(UBound(featsArr) + 1)
                Set featsArr(UBound(featsArr)) = thisFeat
            End If
        End If
    End If

    Dim swSub As SldWorks.Feature
    Set swSub = thisFeat.GetFirstSubFeature()
    While Not swSub Is Nothing
        CollectFeature swSub, featsArr, hasAny, typeName
        Set swSub = swSub.GetNextSubFeature()
    Wend

End Sub

' Tek parca export: aktivasyon + config degisimi minimumda, UI kapali
' (conf = ProcessOneFile'da cozulmus efektif ad; burada tekrar switch gerekmez.)
Function ExportFlatPattern(part As SldWorks.PartDoc, flatPattern As SldWorks.Feature, _
                           outFilePath As String, opts As Long, conf As String, _
                           ByVal openedHere As Boolean) As Boolean

    ExportFlatPattern = False

    Dim swModel As SldWorks.ModelDoc2
    Set swModel = part

    Dim wasHidden As Boolean: wasHidden = False
    Dim switchedConf As Boolean: switchedConf = False
    Dim curConf As String: curConf = ""

    On Error GoTo fail_

    If False = swModel.Visible Then
        wasHidden = True
        swModel.Visible = True
    End If

    swApp.ActivateDoc3 swModel.GetPathName(), False, _
        swRebuildOnActivation_e.swDontRebuildActiveDoc, 0

    On Error GoTo fail_

    curConf = swModel.ConfigurationManager.ActiveConfiguration.Name
    If UCase(curConf) <> UCase(conf) Then ' harf farki gereksiz switch kirletmesin
        If False = swModel.ShowConfiguration2(conf) Then
            Err.Raise vbError, "", "Konfigurasyon acilamadi: " & conf
        End If
        switchedConf = True
    End If

    CreateDirectories Left(outFilePath, InStrRev(outFilePath, "\"))

    Dim modelPath As String
    modelPath = part.GetPathName()
    If modelPath = "" Then
        Err.Raise vbError, "", "Parca kaydedilmemis"
    End If

    If False <> flatPattern.Select2(False, -1) Then
        If False <> part.ExportToDWG2(outFilePath, modelPath, _
                swExportToDWG_e.swExportToDWG_ExportSheetMetal, True, Empty, False, False, opts, Empty) Then
            ExportFlatPattern = True
        End If
    End If

    ' Fallback: eski saglam metod
    If False = ExportFlatPattern Then
        On Error Resume Next
        If False <> part.ExportFlatPatternView(outFilePath, opts) Then
            If FileExists(outFilePath) Then ExportFlatPattern = True
        End If
        On Error GoTo fail_
    End If

    GoTo cleanup_

fail_:
    ExportFlatPattern = False
    On Error Resume Next
    LogLine "[EXPORT-EXC] " & outFilePath & ": " & Err.Description

cleanup_:
    On Error Resume Next
    ' Sadece odunc aldigimiz (zaten acik olan) dokumanin konfigurasyonunu + gorunurlugunu geri al
    If switchedConf And False = openedHere And curConf <> "" Then
        swModel.ShowConfiguration2 curConf
    End If
    If wasHidden And False = openedHere Then
        swModel.Visible = False
    End If
    Set swModel = Nothing

End Function

' --- Dosya / path / property yardimcilari ---

' Sabit on eki tarihli kokle degistirir (sablonun geri kalani aynen korunur).
Function DatedTemplate() As String
    DatedTemplate = gOutRoot & Mid(OUT_NAME_TEMPLATE, Len("Lazer_Kesim&Bukum") + 1)
End Function

Function ComposeOutFileName(template As String, rootModel As SldWorks.ModelDoc2, _
    sheetMetalModel As SldWorks.ModelDoc2, conf As String, _
    flatPatternFeat As SldWorks.Feature, cutListFeat As SldWorks.Feature) As String

    If gRe Is Nothing Then
        Set gRe = CreateObject("VBScript.RegExp")
        gRe.Global = True: gRe.IgnoreCase = True: gRe.Pattern = "<[^>]*>"
    End If

    Dim matches As Object
    Set matches = gRe.Execute(template)

    Dim outFileName As String
    outFileName = template

    Dim i As Long
    For i = matches.Count - 1 To 0 Step -1
        Dim m As Object
        Set m = matches.Item(i)
        Dim tokenName As String
        tokenName = Mid(m.Value, 2, Len(m.Value) - 2)
        outFileName = Left(outFileName, m.FirstIndex) & _
            ResolveToken(tokenName, rootModel, sheetMetalModel, conf, flatPatternFeat, cutListFeat) & _
            Right(outFileName, Len(outFileName) - (m.FirstIndex + m.Length))
    Next i

    ComposeOutFileName = ReplaceInvalidPathSymbols(GetFullPath(rootModel, outFileName))

End Function

Function ReplaceInvalidPathSymbols(path As String) As String
    Const REPLACE_SYMB As String = "_"
    Dim res As String, drive As String
    If IsPathUnc(path) Then
        drive = ""
        res = path
    ElseIf Mid(path, 2, 1) = ":" Then
        drive = Left(path, 3)
        res = Mid(path, 4)
    Else
        drive = ""
        res = path
    End If
    Dim invalidSymbols As Variant
    invalidSymbols = Array("/", ":", "*", "?", """", "<", ">", "|")
    Dim i As Long
    For i = 0 To UBound(invalidSymbols)
        res = Replace(res, CStr(invalidSymbols(i)), REPLACE_SYMB)
    Next i
    ReplaceInvalidPathSymbols = drive + res
End Function

Function ResolveToken(token As String, rootModel As SldWorks.ModelDoc2, _
    sheetMetalModel As SldWorks.ModelDoc2, conf As String, _
    flatPatternFeat As SldWorks.Feature, cutListFeat As SldWorks.Feature) As String

    Const FILE_NAME_TOKEN As String = "_FileName_"
    Const ASSM_FILE_NAME_TOKEN As String = "_AssmFileName_"
    Const FEAT_NAME_TOKEN As String = "_FeatureName_"
    Const CONF_NAME_TOKEN As String = "_ConfName_"
    Const PRP_TOKEN As String = "$PRP:"
    Const CUT_LIST_PRP_TOKEN As String = "$CLPRP:"
    Const ASM_PRP_TOKEN As String = "$ASSMPRP:"

    Select Case LCase(token)
        Case LCase(FILE_NAME_TOKEN)
            ResolveToken = GetFileNameWithoutExtension(sheetMetalModel.GetPathName())
        Case LCase(FEAT_NAME_TOKEN)
            ResolveToken = flatPatternFeat.Name
        Case LCase(CONF_NAME_TOKEN)
            ResolveToken = conf
        Case LCase(ASSM_FILE_NAME_TOKEN)
            If rootModel.GetPathName() = "" Then
                Err.Raise vbError, "", "Assembly kayitli olmali (" & ASSM_FILE_NAME_TOKEN & ")"
            End If
            ResolveToken = GetFileNameWithoutExtension(rootModel.GetPathName())
        Case Else
            Dim prpName As String
            If LCase(Left(token, Len(PRP_TOKEN))) = LCase(PRP_TOKEN) Then
                prpName = Right(token, Len(token) - Len(PRP_TOKEN))
                ResolveToken = GetModelPropertyValue(sheetMetalModel, conf, prpName)
            ElseIf LCase(Left(token, Len(ASM_PRP_TOKEN))) = LCase(ASM_PRP_TOKEN) Then
                prpName = Right(token, Len(token) - Len(ASM_PRP_TOKEN))
                ResolveToken = GetModelPropertyValue(rootModel, _
                    rootModel.ConfigurationManager.ActiveConfiguration.Name, prpName)
            ElseIf LCase(Left(token, Len(CUT_LIST_PRP_TOKEN))) = LCase(CUT_LIST_PRP_TOKEN) Then
                prpName = Right(token, Len(token) - Len(CUT_LIST_PRP_TOKEN))
                ResolveToken = GetPropertyValue(cutListFeat.CustomPropertyManager, prpName)
                If ResolveToken = "" Then
                    If InStr(LCase(prpName), "kal") > 0 Or InStr(LCase(prpName), "thick") > 0 Then
                        ResolveToken = GetSheetMetalThicknessMM(sheetMetalModel)
                    End If
                ElseIf InStr(LCase(prpName), "kal") > 0 Or InStr(LCase(prpName), "thick") > 0 Then
                    ResolveToken = Replace(ResolveToken, ",", ".") ' ondalik nokta: klasor birligi (1,5 -> 1.5)
                End If
            Else
                Err.Raise vbError, "", "Bilinmeyen token: " & token
            End If
    End Select

End Function

Function GetModelPropertyValue(model As SldWorks.ModelDoc2, confName As String, prpName As String) As String
    Dim prpVal As String
    Dim mgr As SldWorks.CustomPropertyManager
    Set mgr = model.Extension.CustomPropertyManager(confName)
    prpVal = GetPropertyValue(mgr, prpName)
    If prpVal = "" Then
        Set mgr = model.Extension.CustomPropertyManager("")
        prpVal = GetPropertyValue(mgr, prpName)
    End If
    GetModelPropertyValue = prpVal
End Function

Function GetPropertyValue(custPrpMgr As SldWorks.CustomPropertyManager, prpName As String) As String
    Dim resVal As String
    On Error Resume Next
    resVal = custPrpMgr.Get(prpName)
    ' SW2014 tek-argumanli Get, baglantili degeri HAM metin doner (ornek:
    ' "SW-Sac Levha Kalinligi@@@Kesim Listesi Ogesi1@KOD.SLDPRT"). "@@@"
    ' iceren deger cozulememistir -> bos say ki geometrik yedek devreye girsin.
    If InStr(resVal, "@@@") > 0 Then resVal = ""
    GetPropertyValue = resVal
End Function

' Kesim-listesi ozelligi bos ise Sac-Levha unsurundan gercek kalinligi (mm) okur.
Function GetSheetMetalThicknessMM(model As SldWorks.ModelDoc2) As String
    On Error Resume Next
    GetSheetMetalThicknessMM = ""
    Dim swFeat As SldWorks.Feature
    Set swFeat = model.FirstFeature()
    Do While Not swFeat Is Nothing
        If LCase(swFeat.GetTypeName2()) = "sheetmetal" Then
            Dim smd As SldWorks.SheetMetalFeatureData
            Set smd = swFeat.GetDefinition()
            If Not smd Is Nothing Then
                Dim tmm As Double
                tmm = smd.Thickness * 1000#
                If Abs(tmm - Round(tmm)) < 0.001 Then
                    GetSheetMetalThicknessMM = CStr(CLng(Round(tmm)))
                Else
                    GetSheetMetalThicknessMM = Replace(CStr(Round(tmm * 100#) / 100#), ",", ".") ' TR-locale virgulu -> nokta
                End If
                Exit Function
            End If
        End If
        Set swFeat = swFeat.GetNextFeature()
    Loop
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

Function GetFullPath(model As SldWorks.ModelDoc2, path As String)
    GetFullPath = path
    If IsPathRelative(path) Then
        If Left(path, 1) <> "\" Then path = "\" & path
        Dim modelPath As String, modelDir As String
        modelPath = model.GetPathName()
        modelDir = Left(modelPath, InStrRev(modelPath, "\") - 1)
        GetFullPath = modelDir & path
    End If
End Function

Function IsPathRelative(path As String)
    IsPathRelative = Mid(path, 2, 1) <> ":" And Not IsPathUnc(path)
End Function

Function IsPathUnc(path As String)
    IsPathUnc = Left(path, 2) = "\\"
End Function

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
    Set ts = gFso.OpenTextFile(BASE_DIR & "\export_raporu_liste.txt", 8, True)
    ts.WriteLine ""
    ts.WriteLine "========================================================"
    ts.WriteLine "DXF LISTE RAPORU v4-list - " & Format(Now, "yyyy-MM-dd HH:mm:ss")
    ts.WriteLine "Satir: " & gTotalInst & " | DXF-OK: " & gOk & " | PDF-OK: " & gPdf & " | Mevcut-Atla: " & gSkip & " | Sac-degil: " & gNotSheet & " | Hata: " & gFail
    ts.WriteLine "========================================================"
    Dim j As Long
    For j = 1 To gLog.Count
        ts.WriteLine gLog(j)
    Next j
    ts.WriteLine ""
    ts.Close
End Sub

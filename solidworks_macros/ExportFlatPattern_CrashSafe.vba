' =========================================================================
' DXF FLAT-PATTERN EXPORT - CRASH-SAFE SURUM (SolidWorks 2014 uyumlu)
' Kaynak: Xarial codestack ornegi (2022) + crash-safe rewrite
' Neden rewrite: orijinal makro buyuk montajda su 4 yuzden coker:
'   1) ResolveAllLightWeightComponents -> tum montaji mideye indirir
'   2) Her componentte GetBodies3 -> tum govdeleri yukler
'   3) Her SolidBodyFolder'da UpdateCutList -> her saci rebuild eder
'   4) Tek hatada tum kosu abort (per-part izolasyon yok)
' Bu surumde: resolve YOK, govde taramasi YOK, zorunlu rebuild YOK,
' parcalar TEKER TEKER gorunmez acilip kapatilir, hata izole edilir.
' SALT-OKUNUR garantisi: parca ReadOnly acilir, Save* cagrisi YOK, kir bayragi iade edilir.
' Kullanim: montaji LIGHTWEIGHT + Large Assembly Mode'da ac, makroyu calistir.
' Kaldigin yerden devam eder (SKIP_EXISTING_FILES = True).
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
    ' (ExportBoundingBox=2048 KALDIRILDI v11: 2014 API'sinde yok, dis danisman bulgusu)
End Enum

' --- AYARLAR ---
Const SKIP_EXISTING_FILES As Boolean = True
Const OUT_NAME_TEMPLATE As String = "DXFs\<$PRP:Malzeme>\<$CLPRP:Sac Levha Kalınlığı>\<_FileName_>.dxf"
Const FLAT_PATTERN_OPTIONS As Long = SheetMetalOptions_e.ExportFlatPatternGeometry
Const STATUS_EVERY As Long = 5   ' her N parcada DoEvents (nefes)
Const FILES_PER_RUN As Long = 30 ' v15: bir kostuda en fazla bu kadar dosya ACILIR, sonra guvenli dur (SW'yi kapatip tekrar calistir)
Dim gNRun As Long ' v15: bu kostuda acilan dosya sayaci
' Cut-list property'ler bos geliyorsa True yap (YAVAS, rebuild eder). Once False dene.
Const ALLOW_CUTLIST_UPDATE As Boolean = False

Dim swApp As SldWorks.SldWorks
Dim gLog As Collection
Dim gOk As Long, gSkip As Long, gFail As Long, gNotSheet As Long
Dim gDiagDone As Boolean ' ilk atlanan parcanin tani dokumu bir kez yapilir
Dim gTotalInst As Long, gTotalKeys As Long ' ornek sayisi (tekrar dahil) / benzersiz dosya
Dim gNEnter As Long, gNNothing As Long, gNSupp As Long, gNNoPath As Long ' tani sayaclari
Dim gOpened As Collection ' bizim actigimiz dosya yollari (son supurme icin)
Dim gNLeftOpen As Long ' kapanmadan kalan belge sayisi
Dim gRe As Object, gFso As Object ' tek seferlik COM nesneleri (RegExp + FileSystemObject)
Dim gLogPath As String ' anlik iz surumu (cokus guvenli log yolu)

' Anlik iz: her satir hem hafizaya hem dosyaya yazilir (cokuste tani kaybolmaz).
' Dosya her seferinde acilip kapatilir -> sert cokuste bile iz durur (v14).
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
    gOk = 0: gSkip = 0: gFail = 0: gNotSheet = 0: gDiagDone = False: gTotalInst = 0: gTotalKeys = 0
    gNEnter = 0: gNNothing = 0: gNSupp = 0: gNNoPath = 0
    Set gOpened = New Collection: gNLeftOpen = 0
    Set gRe = CreateObject("VBScript.RegExp")
    gRe.Global = True: gRe.IgnoreCase = True: gRe.Pattern = "<[^>]*>"
    Set gFso = CreateObject("Scripting.FileSystemObject")

    On Error GoTo catch_

    Dim swModel As SldWorks.ModelDoc2
    Set swModel = swApp.ActiveDoc

    If swModel Is Nothing Then
        Err.Raise vbError, "", "Once montaj veya parca dosyasini acin"
    End If

    ' Iz dosyasini BASLANGICTA ac: kosan surum + faz-1 izi cokuste bile durur (v14)
    On Error Resume Next
    gLogPath = Left(swModel.GetPathName(), InStrRev(swModel.GetPathName(), "\") - 1) & "\export_raporu_crashsafe.txt"
    If gLogPath <> "\export_raporu_crashsafe.txt" Then
        Dim ts0 As Object
        Set ts0 = gFso.OpenTextFile(gLogPath, 8, True)
        ts0.WriteLine ""
        ts0.WriteLine "=== DXF EXPORT v15 BASLADI - " & Format(Now, "yyyy-MM-dd HH:mm:ss") & " ==="
        ts0.Close
    Else
        gLogPath = ""
    End If
    On Error GoTo catch_

    If swModel.GetType() = swDocumentTypes_e.swDocASSEMBLY Then

        Dim swAssy As SldWorks.AssemblyDoc
        Set swAssy = swModel

        ' KRITIK: ResolveAll YOK. Montaj lightweight kalir.
        Dim keys As Object ' Scripting.Dictionary: key -> Array(path, conf)
        Set keys = CollectUniquePartKeys(swAssy)
        gTotalKeys = keys.Count ' benzersiz dosya sayisi

        If keys.Count = 0 Then
            swApp.SendMsgToUser2 "Islenecek parca bulunamadi (hepsi suppressed veya SLDPRT degil).", _
                swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
            GoTo finally_
        End If

        Dim arrKeys As Variant
        arrKeys = keys.keys

        Dim i As Long
        For i = 0 To UBound(arrKeys)
            Dim vals As Variant
            vals = keys(arrKeys(i))
            LogLine "[DOSYA] " & CStr(vals(0)) & " [" & CStr(vals(1)) & "]"
            ProcessOneFile swModel, CStr(vals(0)), CStr(vals(1)), i + 1, keys.Count
            If gNRun >= FILES_PER_RUN Then
                LogLine "[DURAKLATILDI] Bu kostuda " & gNRun & " dosya acildi, bellek sismeden duruldu. SW'yi KAPATIP tekrar calistirin, kaldigi yerden devam eder."
                Exit For
            End If

            If (i + 1) Mod STATUS_EVERY = 0 Then
                DoEvents ' (2014'te status-bar API yok; sadece nefes aldir)
            End If
        Next i

    ElseIf swModel.GetType() = swDocumentTypes_e.swDocPART Then

        Dim swPart As SldWorks.PartDoc
        Set swPart = swModel
        gTotalKeys = 1: gTotalInst = 1 ' tek dosya modu
        ProcessSheetMetalModel swModel, swModel, _
            swModel.ConfigurationManager.ActiveConfiguration.Name, False

    Else
        Err.Raise vbError, "", "Sadece montaj ve parca desteklenir"
    End If

    GoTo finally_

catch_:
    LogLine "[KRITIK] " & Err.Description
finally_:
    On Error Resume Next
    Call SweepOpenedDocs ' acik kalanlari kapat (dogrulamali)
    WriteLogFile swApp.ActiveDoc
    Dim msg As String
    msg = "Islem tamamlandi!" & vbCrLf & vbCrLf & _
        "- Taranan ornek / benzersiz dosya: " & gTotalInst & " / " & gTotalKeys & vbCrLf & _
        "- Olusturulan DXF: " & gOk & vbCrLf & _
        "- Zaten mevcut (Atlandi): " & gSkip & vbCrLf & _
        "- Sac degil (Atlandi): " & gNotSheet & vbCrLf & _
        "- Hatali: " & gFail & vbCrLf & _
        "- Kapanmadan kalan belge: " & gNLeftOpen
    If gNRun >= FILES_PER_RUN Then
        msg = msg & vbCrLf & vbCrLf & "DURAKLATILDI: bellek korumasi. SW'yi kapatip makroyu tekrar calistirin."
    End If
    If gFail > 0 Or gLog.Count > 0 Then
        msg = msg & vbCrLf & vbCrLf & "Detay: montaj klasorunde export_raporu_crashsafe.txt"
    End If
    swApp.SendMsgToUser2 msg, swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
    Set gLog = Nothing

End Sub

' --- FAZ 1: dosya acmadan benzersiz parca listesi topla ---
' GetComponents(False) lightweight alt montajlarin icini VERMEZ (log kaniti: 264 vida
' disinda her sey kayip). Bu yuzden agactan recursive inilir: GetComponents(True) + GetChildren.
' Govdeye HIC dokunulmaz, resolve YOK -> bellek sismez. Dongu korumasi: visited sozlugu.
Function CollectUniquePartKeys(assy As SldWorks.AssemblyDoc) As Object

    Dim dict As Object
    Set dict = CreateObject("Scripting.Dictionary")
    dict.CompareMode = 1 ' vbTextCompare

    Dim visited As Object
    Set visited = CreateObject("Scripting.Dictionary")
    visited.CompareMode = 1

    Dim vTop As Variant
    vTop = assy.GetComponents(True) ' sadece en ust seviye

    If Not IsEmpty(vTop) Then
        Dim i As Long
        Dim swTop As SldWorks.Component2
        For i = 0 To UBound(vTop)
            Set swTop = vTop(i)
            Call CollectComp(swTop, dict, visited)
        Next i
    End If

    Set CollectUniquePartKeys = dict

End Function

' Tek bileseni isle: parcaysa listeye ekle, montajsa cocuklara in (recursive, tek-tek cozumlemeli).
Sub CollectComp(swComp As SldWorks.Component2, dict As Object, visited As Object)
    On Error Resume Next ' tek bozuk bilesen butunu durdurmasin
    gNEnter = gNEnter + 1
    If swComp Is Nothing Then gNNothing = gNNothing + 1: Exit Sub
    If swComp.IsSuppressed() Then gNSupp = gNSupp + 1: Exit Sub
    Dim p As String
    p = Trim(swComp.GetPathName())
    ' Hafif proxy'de yol bos gelebilir -> yolu bos VE hafifse cozup tekrar oku.
    ' (Yolu dolu parcaya dokunma: hizli yol. Danisman onerisi + optimizasyon.)
    Dim wasLight As Boolean: wasLight = False
    If p = "" Then
        If swComp.GetSuppression() = swComponentLightweight Then
            wasLight = True
            Call swComp.SetSuppression2(swComponentFullyResolved)
            p = Trim(swComp.GetPathName())
        End If
    End If
    If p = "" Then gNNoPath = gNNoPath + 1: GoTo cleanup_
    If UCase(Right(p, 6)) = "SLDPRT" Then
        gTotalInst = gTotalInst + 1 ' her ornegi say (tekrar dahil)
        Dim c As String
        c = swComp.ReferencedConfiguration
        Dim k As String
        k = p & "||" & UCase(c)
        If Not dict.Exists(k) Then
            dict.Add k, Array(p, c)
        End If
    ElseIf UCase(Right(p, 6)) = "SLDASM" Then
        Dim ak As String
        ak = p & "||" & UCase(swComp.ReferencedConfiguration)
        If visited.Exists(ak) Then Exit Sub ' dongu/tekrar korumasi
        visited.Add ak, 1
        If False = FileExists(p) Then
            LogLine "[KAYIP-REF] " & p & " [" & UCase(swComp.ReferencedConfiguration) & "] (diskte yok, coz denemedik)"
            Exit Sub
        End If
        ' Montaji YOLU DOLU OLSA BILE coz: hafif ebeveynin cocuklari proxy kalabilir (danisman).
        ' Cozulu montajda bu cagri no-op'tur. Tek-tek coz, bitince SADECE biz cozduysek geri hafiflet.
        Dim needLight As Boolean
        needLight = (swComp.GetSuppression() = swComponentLightweight)
        Call swComp.SetSuppression2(swComponentFullyResolved)
        Dim vCh As Variant
        vCh = swComp.GetChildren
        ' Bos dizide UBound Error 9 verir, Resume Next donguyu sessiz atlar -> guvenli sayim (danisman)
        Dim nCh As Long: nCh = 0
        Dim hasChildren As Boolean: hasChildren = False
        If Not IsEmpty(vCh) Then
            Err.Clear
            nCh = UBound(vCh)
            If Err.Number = 0 Then hasChildren = True
            nCh = nCh + 1
        End If
        LogLine "[ALT-MONTAJ] " & p & " [" & UCase(swComp.ReferencedConfiguration) & "] | Cocuk=" & nCh & " | Supp=" & swComp.GetSuppression() & " | HafifCoz=" & needLight
        If hasChildren Then
            Dim t0 As SldWorks.Component2: Set t0 = vCh(0)
            LogLine "[COCUK-0] " & t0.Name2 & " | YolBos=" & (t0.GetPathName() = "")
            Dim j As Long
            Dim swCh As SldWorks.Component2
            For j = 0 To nCh - 1
                Set swCh = vCh(j)
                Call CollectComp(swCh, dict, visited)
            Next j
        End If
        If needLight Then Call swComp.SetSuppression2(swComponentLightweight)
    End If
cleanup_:
    If wasLight Then Call swComp.SetSuppression2(swComponentLightweight)
End Sub

' --- FAZ 2: tek dosyayi gorunmez ac, isle, kapat ---
Sub ProcessOneFile(rootModel As SldWorks.ModelDoc2, partPath As String, conf As String, _
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
        On Error Resume Next
        swApp.DocumentVisible False, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        Set swPartModel = swApp.OpenDoc6(partPath, swDocumentTypes_e.swDocPART, _
            swOpenDocOptions_e.swOpenDocOptions_Silent Or swOpenDocOptions_e.swOpenDocOptions_ReadOnly, _
            conf, errVal, warnVal)
        On Error Resume Next
        swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        If Not swPartModel Is Nothing Then
            openedHere = True
            gOpened.Add partPath ' son supurme listesi
            gNRun = gNRun + 1 ' v15: gercekten acilan her dosya sayilir
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

    ProcessSheetMetalModel rootModel, swPartModel, conf, openedHere

    ' Odunc belgede biz kirlettiysen ve giriste temiz idiyse bayragi geri al (disk'e yazilmaz).
    If False = openedHere And borrowedClean Then
        ClearDirtyFlag swPartModel ' v13: gec baglama (2014 imza farki derleme patlatiyordu)
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
    LogLine "[HATA] " & partPath & " (" & conf & "): " & Err.Description
    On Error Resume Next
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

' Ilk atlanan parcanin unsur tip adlarini loga doker ("neden sac degil?" sorusunun cevabi).
' Kendi icinde Resume Next kullanir; cagiran prosedurun hata blogunu etkilemez.
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
                           conf As String, ByVal openedHere As Boolean)

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
            outFile = ComposeOutFileName(OUT_NAME_TEMPLATE, rootModel, sheetMetalModel, conf, swFlatFeat, swCutFeat)

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

    ' Tek cut-list varsa govde eslestirmeye girme: govde yuklemeden ilk klasoru kullan (v10).
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
        ' DIKKAT: orijinal kod her SolidBodyFolder'da UpdateCutList cagiriyordu (rebuild = cokus).
        ' Artik sadece ALLOW_CUTLIST_UPDATE=True ise ve tip CutListFolder araniyorsa guncelle.
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
Function ExportFlatPattern(part As SldWorks.PartDoc, flatPattern As SldWorks.Feature, _
                           outFilePath As String, opts As Long, conf As String, _
                           ByVal openedHere As Boolean) As Boolean

    ExportFlatPattern = False

    Dim swModel As SldWorks.ModelDoc2
    Set swModel = part

    Dim wasHidden As Boolean: wasHidden = False
    ' (v11: FeatureTree/Graphics kapatma kaldirildi — gorunmez belgede etkisiz, danisman)
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

' --- Dosya / path / property yardimcilari (orijinalden, kucuk duzeltmelerle) ---

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
    ' UNC veya surucu harfi: ilk 2 karakteri koru, gerisini temizle
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
                    ' Kesim-listesi ozelligi bu konfigurasyonda bos birakilmis olabilir;
                    ' kalinlik isteniyorsa gercek degeri Sac-Levha unsurundan oku (v7).
                    If InStr(LCase(prpName), "kal") > 0 Or InStr(LCase(prpName), "thick") > 0 Then
                        ResolveToken = GetSheetMetalThicknessMM(sheetMetalModel)
                    End If
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
    custPrpMgr.Get2 prpName, "", resVal
    GetPropertyValue = resVal
End Function

' Kesim-listesi ozelligi bos ise Sac-Levha unsurundan gercek kalinligi (mm) okur.
' Basarisiz olursa "" doner; klasor yine bos kalirsa sorun unsurda/logda aranir.
Function GetSheetMetalThicknessMM(model As SldWorks.ModelDoc2) As String
    On Error Resume Next
    GetSheetMetalThicknessMM = ""
    Dim swFeat As SldWorks.Feature
    Set swFeat = model.FirstFeature()
    Do While Not swFeat Is Nothing
        If LCase(swFeat.GetTypeName()) = "sheetmetal" Then
            Dim smd As SldWorks.SheetMetalFeatureData
            Set smd = swFeat.GetDefinition()
            If Not smd Is Nothing Then
                Dim tmm As Double
                tmm = smd.Thickness * 1000#
                If Abs(tmm - Round(tmm)) < 0.001 Then
                    GetSheetMetalThicknessMM = CStr(CLng(Round(tmm)))
                Else
                    GetSheetMetalThicknessMM = CStr(Round(tmm * 100#) / 100#)
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
    ' v12: Dir bulut-placeholder yollarda yanlis negatif verebilir -> FSO (danisman)
    If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
    FileExists = gFso.FileExists(filePath)
End Function

' Kir-bayragi temizleme: SetSaveFlag imzasi 2014'te farkli (derleme patladi) ->
' gec baglama kullan, surumden bagimsiz; basarisizsa sessiz gec (v6 davranisi).
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

' Bizim actigimiz belgeleri tek tek kapat, kapanmayani say + logla (v8).
' 2014'te CloseDoc kirli (*) belgede sessizce basarisiz olur; dogrulama sart.
Sub CloseDocVerified(docPath As String, docTitle As String)
    On Error Resume Next
    If Right(docTitle, 2) = " *" Then docTitle = Left(docTitle, Len(docTitle) - 2) ' kirli baslik yildizi (2014, danisman)
    swApp.CloseDoc docTitle ' statement olarak cagir: donus degeri surume gore degisir, dogrulama yeterli
    Dim still As Object
    Set still = swApp.GetOpenDocumentByName(docPath)
    If Not still Is Nothing Then
        gNLeftOpen = gNLeftOpen + 1
        LogLine "[KAPAT-HATA] " & docPath
    End If
End Sub

' Kosu sonunda acik kalmis kendi belgelerimizi supur (ana montaj haric hepsi bizimdi).
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

Sub WriteLogFile(activeModel As SldWorks.ModelDoc2)
    On Error Resume Next
    If gLog Is Nothing Then Exit Sub
    If gLog.Count = 0 And gFail = 0 Then Exit Sub
    If activeModel Is Nothing Then Exit Sub
    Dim asmPath As String
    asmPath = activeModel.GetPathName()
    If asmPath = "" Then Exit Sub
    Dim dirP As String
    dirP = Left(asmPath, InStrRev(asmPath, "\") - 1)
    If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
    Dim ts As Object
    Set ts = gFso.OpenTextFile(dirP & "\export_raporu_crashsafe.txt", 8, True)
    ts.WriteLine ""
    ts.WriteLine "========================================================"
    ts.WriteLine "DXF EXPORT RAPORU v14 - " & Format(Now, "yyyy-MM-dd HH:mm:ss")
    ts.WriteLine "Ornek: " & gTotalInst & " | Dosya: " & gTotalKeys & " | OK: " & gOk & " | Mevcut-Atla: " & gSkip & " | Sac-degil: " & gNotSheet & " | Hata: " & gFail
    ts.WriteLine "TANI-SAYAC: Giris=" & gNEnter & " | Nothing=" & gNNothing & " | Suppressed=" & gNSupp & " | Yolsuz=" & gNNoPath
    ts.WriteLine "========================================================"
    Dim j As Long
    For j = 1 To gLog.Count
        ts.WriteLine gLog(j)
    Next j
    ts.WriteLine ""
    ts.Close
End Sub

' =========================================================================
' SOLIDWORKS PDF EXPORT BY CUSTOM PROPERTY (uretim_sekli)
' =========================================================================
' Bu makro, aktif montajdaki tüm parçaları tarar, teknik resimlerini bulur
' ve "uretim_sekli" özelliğine göre klasörleyerek PDF export eder.
'
' Özellikler:
'   - Daha önce oluşturulmuş PDF'leri atlar (artımlı export)
'   - Teknik resmi olmayan parçaları export_raporu.txt'ye yazar
' =========================================================================

Dim swApp As SldWorks.SldWorks
Dim swModel As SldWorks.ModelDoc2
Dim swAsm As SldWorks.AssemblyDoc
Dim fso As Object
Dim baseExportPath As String
Dim processedPats As Object ' Scripting.Dictionary for deduplication

' Sayaçlar ve rapor
Dim exportedCount As Long
Dim skippedCount As Long
Dim missingCount As Long
Dim reportLines As Collection ' VBA Collection for report lines

Sub Main()
    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    
    If swModel Is Nothing Then
        MsgBox "Lütfen bir montaj dosyası açın.", vbCritical
        Exit Sub
    End If
    
    If swModel.GetType <> swDocASSEMBLY Then
        MsgBox "Bu makro sadece montaj dosyalarında çalışır.", vbCritical
        Exit Sub
    End If

    ' Export klasörünü ayarla (Montaj ile aynı yerde PDF_EXPORT klasörü)
    Dim asmPath As String
    asmPath = swModel.GetPathName
    If asmPath = "" Then
        MsgBox "Lütfen önce montaj dosyasını kaydedin.", vbExclamation
        Exit Sub
    End If
    
    Set fso = CreateObject("Scripting.FileSystemObject")
    baseExportPath = fso.GetParentFolderName(asmPath) & "\PDF_EXPORT"
    
    If Not fso.FolderExists(baseExportPath) Then
        fso.CreateFolder (baseExportPath)
    End If

    ' Her çalıştırmada önceki hafızayı temizle
    If Not processedPats Is Nothing Then
        processedPats.RemoveAll
    End If
    Set processedPats = CreateObject("Scripting.Dictionary")
    
    ' Sayaçları sıfırla
    exportedCount = 0
    skippedCount = 0
    missingCount = 0
    Set reportLines = New Collection
    
    ' Başla
    swApp.SendMsgToUser2 "Export işlemi başlıyor. Lütfen bekleyin...", swMbInformation, swMbOk
    
    ' Ana montajın kendisini de işle
    ProcessModel swModel
    
    ' Tüm bileşenleri tara (Ağaç yapısı üzerinden)
    Dim swConf As SldWorks.Configuration
    Dim swRootComp As SldWorks.Component2
    Set swConf = swModel.GetActiveConfiguration
    Set swRootComp = swConf.GetRootComponent3(True)
    
    Dim vComps As Variant
    Dim k As Long
    Dim mainChildComp As SldWorks.Component2
    vComps = swRootComp.GetChildren
    If Not IsEmpty(vComps) Then
        For k = 0 To UBound(vComps)
            Set mainChildComp = vComps(k)
            TraverseComponentStructure mainChildComp
        Next k
    End If
    
    ' Rapor dosyasını yaz
    WriteReport
    
    ' Özet mesajı göster
    Dim summary As String
    summary = "İşlem tamamlandı!" & vbCrLf & vbCrLf & _
              "- Oluşturulan PDF: " & exportedCount & vbCrLf & _
              "- Zaten mevcut (atlandı): " & skippedCount & vbCrLf & _
              "- Teknik resim eksik: " & missingCount & vbCrLf & vbCrLf & _
              "PDF klasörü: " & baseExportPath
    
    If missingCount > 0 Then
        summary = summary & vbCrLf & "Detaylı rapor: " & baseExportPath & "\export_raporu.txt"
    End If
    
    swApp.SendMsgToUser2 summary, swMbInformation, swMbOk
    
    ' Hafızayı temizle (bellek sızıntılarını ve sonraki çalışmalarda oluşabilecek hataları engelle)
    If Not processedPats Is Nothing Then
        processedPats.RemoveAll
    End If
    Set processedPats = Nothing
    Set reportLines = Nothing
    Set fso = Nothing
End Sub

Sub TraverseComponentStructure(ByVal swComp As SldWorks.Component2)
    Dim vComps As Variant
    Dim childComp As SldWorks.Component2
    Dim i As Long
    
    ' Component suppressed (pasif) değilse işle
    If swComp.GetSuppression <> swComponentSuppressed Then
        Dim compModel As SldWorks.ModelDoc2
        Dim wasOpenedManually As Boolean
        wasOpenedManually = False
        Set compModel = swComp.GetModelDoc2
        
        ' Eğer parça Lightweight ise (Hafif modda yüklendiyse) model datası boştur.
        ' Özellikleri okumak için Resolved (Çözümlenmiş) duruma getirilmesi gerekir.
        If compModel Is Nothing And (swComp.GetSuppression = 2 Or swComp.GetSuppression = 4) Then ' swComponentLightweight = 2
            swComp.SetSuppression2 1 ' swComponentResolved = 1
            Set compModel = swComp.GetModelDoc2
        End If
        
        ' 3. AŞAMA DÜZELTME: Hala Nothing ise (Büyük Montaj Modunda açılmışsa) arka planda sessizce aç
        If compModel Is Nothing Then
            Dim compPath As String
            compPath = swComp.GetPathName
            If compPath <> "" And fso.FileExists(compPath) Then
                Dim err As Long
                Dim warn As Long
                Dim docType As Long
                
                If UCase(Right(compPath, 6)) = "SLDASM" Then
                    docType = swDocASSEMBLY
                Else
                    docType = swDocPART
                End If
                
                ' Dosyayı arka planda sessizce aç (Özellikleri okumak için)
                Set compModel = swApp.OpenDoc6(compPath, docType, swOpenDocOptions_Silent Or swOpenDocOptions_ReadOnly, "", err, warn)
                
                If Not compModel Is Nothing Then
                    wasOpenedManually = True
                End If
            End If
        End If
        
        If Not compModel Is Nothing Then
            ProcessModel compModel
            
            ' Eğer biz geçici olarak açtıysak RAM dolmasın diye işi bitince kapatalım
            If wasOpenedManually Then
                swApp.CloseDoc compModel.GetTitle
            End If
        Else
            ' Hala Nothing ise (Sanal bileşenler, kaydedilmemiş parçalar vs.)
            If swComp.GetPathName <> "" Then
                reportLines.Add "[UYARI] """ & swComp.Name2 & """ isimli bilesin fiziksel dosyasina (" & swComp.GetPathName & ") erisilemedi."
            End If
        End If
        
        ' Alt seviyelere (çocuklara) in
        vComps = swComp.GetChildren
        If Not IsEmpty(vComps) Then
            For i = 0 To UBound(vComps)
                Set childComp = vComps(i)
                TraverseComponentStructure childComp
            Next i
        End If
    End If
End Sub

Sub ProcessModel(model As ModelDoc2)
    Dim modelPath As String
    modelPath = model.GetPathName
    
    ' Zaten işlendiyse atla
    If processedPats.Exists(modelPath) Then Exit Sub
    processedPats.Add modelPath, True
    
    Dim partName As String
    partName = fso.GetBaseName(modelPath)
    
    ' 1. uretim_sekli CP'sini al -> hedef klasör ve PDF yolunu hesapla
    Dim uretimSekli As String
    uretimSekli = Trim(GetCustomProperty(model, "uretim_sekli"))
    If uretimSekli = "" Then uretimSekli = "UNKNOWN"
    
    Dim targetFolder As String
    targetFolder = baseExportPath & "\" & CleanFileName(uretimSekli)
    
    ' Klasörü oluştur (henüz yoksa)
    If Not fso.FolderExists(targetFolder) Then
        fso.CreateFolder (targetFolder)
    End If
    
    Dim pdfPath As String
    pdfPath = targetFolder & "\" & partName & ".pdf"
    
    ' 2. PDF zaten var mı? -> Atla
    If fso.FileExists(pdfPath) Then
        skippedCount = skippedCount + 1
        ' [DEBUG] Kullanıcının silmesine rağmen neden atladığını anlamak için tam yolu rapora yazıyoruz
        reportLines.Add "[ATLANDI] """ & partName & """ zaten mevcut -> " & pdfPath
        Exit Sub
    End If
    
    ' 3. Teknik resim dosyası var mı?
    Dim drwPath As String
    drwPath = fso.GetParentFolderName(modelPath) & "\" & partName & ".SLDDRW"
    
    If Not fso.FileExists(drwPath) Then
        ' Teknik resim bulunamadı -> rapora ekle
        missingCount = missingCount + 1
        Dim reportLine As String
        reportLine = "[EKSIK] """ & partName & """ parçasının PDF'i (" & CleanFileName(uretimSekli) & ") klasörüne yazılamadı - Teknik resim dosyası (.SLDDRW) yok."
        reportLines.Add reportLine
        Exit Sub
    End If
    
    ' 4. Teknik resmi aç ve PDF'e export et
    ExportToPDF drwPath, pdfPath, partName
End Sub

Sub ExportToPDF(drwPath As String, pdfPath As String, partName As String)
    Dim swDrw As SldWorks.ModelDoc2
    Dim errors As Long
    Dim warnings As Long
    
    ' Teknik resmi sessizce aç
    Set swDrw = swApp.OpenDoc6(drwPath, swDocDRAWING, swOpenDocOptions_Silent, "", errors, warnings)
    
    If Not swDrw Is Nothing Then
        ' PDF olarak kaydet
        Dim swExportData As SldWorks.ExportPdfData
        Set swExportData = swApp.GetExportFileData(swExportData_Pdf)
        
        Dim saveStatus As Boolean
        saveStatus = swDrw.Extension.SaveAs(pdfPath, swSaveAsCurrentVersion, swSaveAsOptions_Silent, swExportData, errors, warnings)
        
        ' Kapat (Hata almamak için ModelDoc path adından kapatılabilir)
        swApp.CloseDoc swDrw.GetTitle
        
        If saveStatus And fso.FileExists(pdfPath) Then
            exportedCount = exportedCount + 1
        Else
            ' Kayıt başarısız olduysa raporla
            reportLines.Add "[HATA] """ & partName & """ teknik resmi açıldı ancak PDF kaydedilemedi. (Sessiz modda hata oluşmuş olabilir veya dosya açık kalmış olabilir)"
            missingCount = missingCount + 1
        End If
    Else
        reportLines.Add "[HATA] """ & partName & """ teknik resmi mevcut ama makro tarafından açılamadı. (SolidWorks arka planda dosyayı kilitli tutuyor olabilir)"
        missingCount = missingCount + 1
    End If
End Sub

Function GetCustomProperty(model As ModelDoc2, propName As String) As String
    Dim val As String
    Dim resVal As String
    Dim swCustProp As SldWorks.CustomPropertyManager
    
    ' Önce konfigürasyona özel olanı dene, sonra genel (Custom) olanı
    Set swCustProp = model.Extension.CustomPropertyManager(model.ConfigurationManager.ActiveConfiguration.Name)
    swCustProp.Get4 propName, False, val, resVal
    
    If resVal = "" Then
        Set swCustProp = model.Extension.CustomPropertyManager("")
        swCustProp.Get4 propName, False, val, resVal
    End If
    
    GetCustomProperty = resVal
End Function

Function CleanFileName(fileName As String) As String
    Dim invalidChars As String
    invalidChars = "/\:*?""<>|"
    Dim i As Integer
    Dim result As String
    result = fileName
    For i = 1 To Len(invalidChars)
        result = Replace(result, Mid(invalidChars, i, 1), "_")
    Next i
    CleanFileName = result
End Function

Sub WriteReport()
    ' Sadece eksik varsa rapor dosyası oluştur
    If reportLines Is Nothing Then Exit Sub
    If reportLines.Count = 0 Then Exit Sub
    
    Dim reportPath As String
    reportPath = baseExportPath & "\export_raporu.txt"
    
    Dim ts As Object
    Set ts = fso.OpenTextFile(reportPath, 8, True) ' 8 = ForAppending, True = Create if not exists
    
    ' Tarih/saat damgası ile başlık yaz
    ts.WriteLine ""
    ts.WriteLine "========================================================"
    ts.WriteLine "EXPORT RAPORU - " & Format(Now, "yyyy-MM-dd HH:mm:ss")
    ts.WriteLine "========================================================"
    ts.WriteLine "Toplam Yeni Olusturulan : " & exportedCount
    ts.WriteLine "Toplam Atlanan (Mevcut): " & skippedCount
    ts.WriteLine "Toplam Eksik Tek. Resim: " & missingCount
    ts.WriteLine "========================================================"
    ts.WriteLine ""
    
    Dim j As Long
    For j = 1 To reportLines.Count
        ts.WriteLine reportLines(j)
    Next j
    
    ts.WriteLine ""
    ts.Close
End Sub

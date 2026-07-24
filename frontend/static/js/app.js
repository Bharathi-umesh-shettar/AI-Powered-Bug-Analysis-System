// AI-Powered Bug Analysis System
// Frontend Controller

const API = "";

const $ = (selector) => document.querySelector(selector);


async function fetchJSON(url, options = {}) {

    const response = await fetch(url, options);

    const data = await response.json()
        .catch(() => ({}));

    if (!response.ok) {
        throw new Error(data.error || response.statusText);
    }

    return data;
}



// ================= DASHBOARD =================


async function loadStats(){

    try{

        const data = await fetchJSON("/stats");


        $("#stat-total").textContent =
            data.total_bugs || 0;


        $("#stat-critical").textContent =
            data.critical_bugs || 0;


        $("#stat-kb").textContent =
            data.kb_records || 0;


        $("#stat-dup").textContent =
            data.duplicate_bugs || 0;



        const list = $("#recent-bugs");

        list.innerHTML="";


        (data.recent_bugs || []).forEach((bug)=>{


            const li=document.createElement("li");


            li.innerHTML=`

            <span>
            <strong>#${bug.bug_id}</strong>
            · ${escapeHtml(bug.title)}
            </span>


            <span class="sev">
            ${escapeHtml(bug.severity || "Medium")}
            </span>

            `;


            list.appendChild(li);


        });


    }
    catch(error){

        console.log(
            "Dashboard error:",
            error
        );

    }

}




// ================= SIMILAR BUGS =================


function renderSimilar(bugs){


    const container =
    $("#similar-container");


    if(!container)
        return;



    container.innerHTML="";



    if(!bugs || bugs.length===0){

        container.innerHTML=
        `
        <p class="muted">
        No similar bugs found.
        </p>
        `;

        return;

    }




    bugs.forEach((bug)=>{


        const card =
        document.createElement("div");


        card.className="sim-card";



        card.innerHTML=`

        <h4>
        ${escapeHtml(bug.title)}
        </h4>


        <p>
        Similarity:
        ${bug.similarity_pct || 0}%
        </p>


        <p>
        Severity:
        ${escapeHtml(
        bug.severity || "-"
        )}
        </p>


        <p>
        Component:
        ${escapeHtml(
        bug.component || "-"
        )}
        </p>


        `;


        container.appendChild(card);



    });


}




// ================= SUBMIT BUG =================


document
.getElementById("bug-form")
?.addEventListener(
"submit",
async(event)=>{


event.preventDefault();



const formData =
Object.fromEntries(
new FormData(event.target).entries()
);



try{


const result =
await fetchJSON(
"/submit-bug",
{

method:"POST",

headers:{
"Content-Type":
"application/json"
},


body:
JSON.stringify(formData)

});


currentBugId =
result.bug_id;



renderSimilar(
result.similar_bugs
);



await loadFullAnalysis(
result.bug_id
);



event.target.reset();


loadStats();

loadBugs();

loadRecentAnalyses();



}
catch(error){

alert(error.message);

}



});




// ================= UPLOAD BUG =================


document
.getElementById("upload-form")
?.addEventListener(
"submit",
async(event)=>{


event.preventDefault();


const form =
new FormData(event.target);



try{


const result =
await fetchJSON(
"/upload-bug",
{

method:"POST",

body:form

});



currentBugId =
result.bug_id;



renderSimilar(
result.similar_bugs
);



await loadFullAnalysis(
result.bug_id
);



event.target.reset();



loadStats();

loadBugs();

loadRecentAnalyses();



}
catch(error){

alert(error.message);

}



});
// ================= FULL ANALYSIS =================


let currentBugId = null;



async function loadFullAnalysis(bugId){


    currentBugId = bugId;


    try{


        const analysis =
        await fetchJSON(
            `/analysis/${bugId}`
        );


        renderAnalysis(
            analysis.analysis
        );



        // ROOT CAUSE

        const root =
        await fetchJSON(
        "/root-cause",
        {

            method:"POST",

            headers:{
                "Content-Type":
                "application/json"
            },


            body:
            JSON.stringify({
                bug_id:bugId
            })

        });



        document
        .getElementById(
        "root-cause-container"
        )
        .innerHTML = `


        <div class="analysis-panel">

        <h4>
        🎯 Root Cause
        </h4>


        <p>
        ${escapeHtml(
        root.root_cause || "-"
        )}
        </p>


        <p>
        <b>Failure Point:</b>
        ${escapeHtml(
        root.failure_point || "-"
        )}
        </p>


        <p>
        <b>Exception:</b>
        ${escapeHtml(
        root.exception_type || "-"
        )}
        </p>


        </div>

        `;




        // DUPLICATE DETECTION


        const duplicate =
        await fetchJSON(
        "/duplicate-check",
        {

            method:"POST",

            headers:{
                "Content-Type":
                "application/json"
            },


            body:
            JSON.stringify({
                bug_id:bugId
            })

        });



        document
        .getElementById(
        "duplicate-container"
        )
        .innerHTML = `


        <div class="analysis-panel">

        <h4>
        🔁 Duplicate Detection
        </h4>


        <p>
        <b>Status:</b>
        ${
        duplicate.is_duplicate
        ?
        "Duplicate Found"
        :
        "No Duplicate"
        }

        </p>



        <pre>
        ${escapeHtml(
        JSON.stringify(
        duplicate,
        null,
        2
        ))
        }
        </pre>


        </div>

        `;




        // REMEDIATION


        const recommendation =
        await fetchJSON(
        "/recommendation",
        {

            method:"POST",

            headers:{
            "Content-Type":
            "application/json"
            },


            body:
            JSON.stringify({
                bug_id:bugId
            })

        });



        document
        .getElementById(
        "remediation-container"
        )
        .innerHTML = `


        <div class="analysis-panel">

        <h4>
        🛠 AI Recommendation
        </h4>


        <p>
        ${
        escapeHtml(
        recommendation.recommendation
        ||
        "No recommendation"
        )
        }
        </p>


        </div>

        `;




        // STRUCTURED FINDINGS


        const findings =
        await fetchJSON(
        `/structured-findings/${bugId}`
        );



        document
        .getElementById(
        "structured-findings-container"
        )
        .innerHTML = `


        <pre>
        ${escapeHtml(
        JSON.stringify(
        findings,
        null,
        2
        ))
        }
        </pre>


        `;



    }
    catch(error){


        console.error(
        "Analysis error:",
        error
        );


    }


}




// ================= RECORDS TABLE =================



let allBugs=[];

let page=1;

const PAGE_SIZE=8;



async function loadBugs(){


    try{


        const data =
        await fetchJSON(
        "/all-bugs"
        );


        allBugs =
        data.bugs || [];


        renderTable();



    }
    catch(error){

        console.log(error);

    }


}




function renderTable(){


const search =
$("#search");


const sort =
$("#sort");



if(!search || !sort)
return;



const query =
search.value
.toLowerCase()
.trim();



let rows =
allBugs.filter(
(b)=>

!query ||

(b.title||"")
.toLowerCase()
.includes(query)

||

(b.component||"")
.toLowerCase()
.includes(query)

);



const tbody =
$("#bugs-table tbody");



tbody.innerHTML="";



rows
.slice(
(page-1)*PAGE_SIZE,
page*PAGE_SIZE
)
.forEach(
(bug)=>{


const tr =
document.createElement("tr");



tr.innerHTML=`

<td>
#${bug.bug_id}
</td>


<td>
${escapeHtml(bug.title)}
</td>


<td>
${escapeHtml(
bug.severity || "-"
)}
</td>


<td>
${escapeHtml(
bug.category || "-"
)}
</td>


<td>
${escapeHtml(
bug.component || "-"
)}
</td>


<td>
${escapeHtml(
bug.reporter || "-"
)}
</td>


<td>
${escapeHtml(
bug.created_date || "-"
)}
</td>

`;



tbody.appendChild(tr);



});



}
// ================= SEARCH / PAGINATION =================


$("#search")
?.addEventListener(
"input",
()=>{

page=1;

renderTable();

});


$("#sort")
?.addEventListener(
"change",
renderTable
);



$("#prev")
?.addEventListener(
"click",
()=>{

if(page>1){

page--;

renderTable();

}

});



$("#next")
?.addEventListener(
"click",
()=>{

page++;

renderTable();

}

);





// ================= AI ANALYSIS RENDER =================


function sevClass(severity){

const s =
(severity||"")
.toLowerCase();


if(s==="critical")
return "sev-critical";


if(s==="high")
return "sev-high";


if(s==="medium")
return "sev-medium";


return "sev-low";

}




function renderAnalysis(a){


const box =
document.getElementById(
"analysis-container"
);



if(!a){

box.innerHTML=
`
<p class="muted">
No analysis available
</p>
`;

return;

}




box.innerHTML=

`

<div class="analysis-card">


<h3>
Bug #${a.bug_id}
AI Analysis
</h3>


<p>
<b>Severity:</b>
${escapeHtml(a.severity || "-")}
</p>


<p>
<b>Priority:</b>
${escapeHtml(a.priority || "-")}
</p>


<p>
<b>Component:</b>
${escapeHtml(a.affected_component || "-")}
</p>


<p>
<b>Exception:</b>
${escapeHtml(a.exception_type || "-")}
</p>


<p>
<b>Root Cause:</b>
${escapeHtml(a.root_cause || "-")}
</p>


<p>
<b>Confidence:</b>
${a.confidence || 0}%
</p>


</div>

`;

}




// ================= RECENT ANALYSIS =================



async function loadRecentAnalyses(){


try{


const data =
await fetchJSON(
"/analyses?limit=6"
);



const box =
document.getElementById(
"recent-analyses"
);



if(!box)
return;



box.innerHTML="";



(data.analyses||[])
.forEach(
(a)=>{


const div =
document.createElement("div");


div.className=
"mini-analysis";



div.innerHTML=

`

<h4>
#${a.bug_id}
${escapeHtml(
a.bug_title || ""
)}
</h4>


<p>
${escapeHtml(
a.severity || "-"
)}
</p>


<p>
${a.confidence || 0}%
</p>

`;



box.appendChild(div);



});



}
catch(error){

console.log(error);

}


}





// ================= VALIDATION =================



document
.getElementById(
"run-validation"
)
?.addEventListener(
"click",
async()=>{


try{


const result =
await fetchJSON(
"/validate"
);



document
.getElementById(
"validation-summary"
)
.innerHTML =

`

<div class="card">

<h3>
${result.triage_accuracy_pct || 0}%
</h3>

<p>
Triage Accuracy
</p>


</div>


<div class="card">

<h3>
${result.total_cases || 0}
</h3>

<p>
Test Cases
</p>


</div>

`;



}
catch(error){

alert(error.message);

}



});





// ================= WATCHER =================



async function loadWatcherStatus(){


try{


const status =
await fetchJSON(
"/watcher/status"
);



const text =
document.getElementById(
"watcher-state"
);



if(text){

text.textContent =

`
status:
${status.running ? "🟢 running":"⚪ stopped"}
·
${status.processed_count || 0}
processed
`;

}



}
catch(error){

console.log(error);

}


}




$("#watcher-refresh")
?.addEventListener(
"click",
loadWatcherStatus
);



$("#watcher-scan")
?.addEventListener(
"click",
async()=>{


await fetchJSON(
"/watcher/scan",
{
method:"POST"
}
);


loadWatcherStatus();


loadStats();


loadBugs();


});





// ================= EXPORT =================



$("#export-json")
?.addEventListener(
"click",
()=>{


if(!currentBugId){

alert(
"Submit a bug first"
);

return;

}


window.location.href =
`/export/${currentBugId}.json`;


});




$("#export-csv")
?.addEventListener(
"click",
()=>{


if(!currentBugId){

alert(
"Submit a bug first"
);

return;

}


window.location.href =
`/export/${currentBugId}.csv`;


});




$("#export-pdf")
?.addEventListener(
"click",
()=>{


if(!currentBugId){

alert(
"Submit a bug first"
);

return;

}


window.location.href =
`/export/${currentBugId}.pdf`;


});





// ================= HELPER =================



function escapeHtml(value){

return String(value || "")
.replace(
/[&<>"']/g,
(char)=>

({

"&":"&amp;",
"<":"&lt;",
">":"&gt;",
'"':"&quot;",
"'":"&#39;"

}[char])

);

}




// ================= START =================



loadStats();

loadBugs();

loadRecentAnalyses();

loadWatcherStatus();



setInterval(
()=>{

loadStats();

loadRecentAnalyses();

loadWatcherStatus();

},
5000
);